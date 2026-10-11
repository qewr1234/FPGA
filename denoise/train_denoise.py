"""Train a small DnCNN-style denoiser that the accelerator can run as it is.

    python denoise/train_denoise.py                         # depth 7, 32 channels
    python denoise/train_denoise.py --depth 5 --channels 16 --epochs 2   # quick try

The structure is DnCNN's (Zhang et al. 2017): conv+ReLU, then conv+BN+ReLU
repeated, then a last conv, all 3x3 with zero padding. Three things are changed
to fit the hardware, and each is a property of the core, not a choice:

  * The last layer outputs the CLEAN IMAGE, not the noise. DnCNN predicts the
    noise and subtracts it, but noise is signed and the core applies ReLU to
    every output it produces. A clean pixel is never negative, so ReLU costs
    the clean-image output nothing.
    --residual instead gets DnCNN's noise prediction past the ReLU: the last
    layer becomes a sign pair, (w, b) and (-w, -b), and the host subtracts the
    two ReLU outputs (see Denoiser).
  * --skip feeds the noisy image into the last layer as one more input channel
    (concatenation). That gives the network the easy path DnCNN's residual gives
    it -- "copy the input, then correct it" -- without a subtraction the core
    cannot do. It costs 9 taps on one layer.
  * The input is clipped and quantized to 7 bits during training exactly as it
    will be on the board (common.add_noise), so the network never sees an input
    it will not get.

Training follows DnCNN's data generator: 40x40 patches from the Train400 images
at scales 1, 0.9, 0.8, 0.7, with the 8 flips/rotations, sigma 25, MSE, Adam.
DnCNN draws ~240k patches per epoch; this draws --patches fresh random ones per
epoch (default 32k) so an epoch fits a CPU.

--dilation 1,2,3,4,3,2,1 makes layer i a 3x3 convolution with dilation d_i
(IRCNN, Zhang et al. 2017): the nine taps are d_i pixels apart. K, and so the
board's cycles, do not change -- the host builds the windows (im2col) and the
core sees K values either way -- but the receptive field grows from
1 + 2*depth to 1 + 2*sum(d_i).

--maxout makes every hidden layer compute TWO candidate maps per channel and
keep the larger, max(ReLU(a), ReLU(b)) = ReLU(max(a, b)) (maxout, Goodfellow et
al. 2013, as Max-Feature-Map pairs channel i with channel i+C). The core then
outputs 2C channels while the next layer still reads C, so K does not grow. On
this core a window costs max(K, ceil(COUT/16)*ceil(K/4)) cycles, and for
K = 288 that is 288 for COUT = 32 and for COUT = 64 alike: where the feed
bounds the layer, the second map costs nothing. The max is taken on the host,
in the requantization it already does between layers.

Writes denoise/<name>.pt and denoise/<name>_train.json (curve, Set12 PSNR).

Two ways to decide how long to train:

  --schedule cosine (default): a fixed --epochs, the rate annealed over them.
      How the existing models were trained.
  --schedule plateau: --epochs is only a ceiling. Every --val-every-th training
      image is held out (never sampled for patches) as a VALIDATION set; when its
      PSNR has not improved for --patience epochs the rate is halved, and when it
      has not improved for --stop-patience epochs, or the rate is below --min-lr,
      training stops. The checkpoint written is the best one on validation.
      Set12 is still printed every epoch, but it is a TEST set: nothing is
      decided by it.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from common import HERE, QMAX_A, load_set, psnr, test_noise

sys.path.insert(0, str(HERE.parent/'scripts'))
from cifar_budget import dense_per_group, per_window  # noqa: E402

K_MAX, COUT_MAX = 1152, 128      # what the board build provides
QMIN_W, QMAX_W = -128, 127       # INT8 weights


class Denoiser(nn.Module):
    """residual=False: the last layer outputs the clean image through the core's
    ReLU (optionally with the noisy image as an extra input, skip).

    residual=True: DnCNN's residual learning -- the last layer outputs the noise
    z, linear, and the clean image is x - z. The core cannot output a signed z,
    because it applies ReLU to everything. So the last layer is built as TWO
    output channels with weights (w, b) and (-w, -b): the core returns ReLU(z)
    and ReLU(-z), and the host takes their difference, which is z exactly --
    in float, and in integers too, because both channels share one weight scale.
    The float model below is therefore the plain linear-output DnCNN; nothing
    about the split needs training."""
    def __init__(self, depth=7, channels=32, skip=True, residual=False, unshuffle=False,
                 dilation=None, maxout=False):
        super().__init__()
        self.maxout = bool(maxout)
        m = 2 if self.maxout else 1          # maps computed per channel kept
        self.dilation = [int(d) for d in (dilation or [1]*depth)]
        assert len(self.dilation) == depth and min(self.dilation) >= 1, \
            f'need {depth} dilations >= 1, got {self.dilation}'
        dl = self.dilation
        if residual:
            skip = False                    # the residual already carries the input
        assert not (residual and unshuffle), 'residual with unshuffle is not implemented'
        self.depth, self.channels, self.skip, self.residual = depth, channels, skip, residual
        self.unshuffle = unshuffle
        # unshuffle (FFDNet, Zhang et al. 2018): the image is split into its four
        # 2x2 phases and the network runs on those half-size sub-images, then
        # the four outputs are put back together. A quarter of the windows, each
        # 3x3 tap covering twice the distance.
        self.img_ch = 4 if unshuffle else 1
        c = channels
        self.first = nn.Conv2d(self.img_ch, m*c, 3, padding=dl[0], dilation=dl[0], bias=True)
        self.mid = nn.ModuleList(nn.Conv2d(c, m*c, 3, padding=dl[i+1], dilation=dl[i+1], bias=False)
                                 for i in range(depth-2))
        self.bn = nn.ModuleList(nn.BatchNorm2d(m*c) for _ in range(depth-2))
        self.last = nn.Conv2d(c + (self.img_ch if skip else 0), self.img_ch, 3,
                              padding=dl[-1], dilation=dl[-1], bias=True)

    def forward(self, x):
        if self.unshuffle:
            hh, ww = x.shape[-2:]
            x = F.pad(x, (0, ww % 2, 0, hh % 2), mode='replicate')   # = common.pad_even
            x = F.pixel_unshuffle(x, 2)
        h = self.pick(F.relu(self.first(x)))
        for conv, bn in zip(self.mid, self.bn):
            h = self.pick(F.relu(bn(conv(h))))
        if self.skip:
            h = torch.cat([h, x], 1)
        if self.residual:
            return x - self.last(h)         # ReLU(z) - ReLU(-z) = z, done on the host
        y = F.relu(self.last(h))            # the core's ReLU, on the image itself
        if self.unshuffle:
            y = F.pixel_shuffle(y, 2)[..., :hh, :ww]
        return y

    def pick(self, h):
        """maxout: channel i of the next layer's input is the larger of maps i and i+C."""
        if not self.maxout:
            return h
        c = self.channels
        return torch.maximum(h[:, :c], h[:, c:])

    def graph(self):
        """The chain as a graph (see graph_shapes): every layer reads the one
        before it, the last also the image when skip."""
        c, g, m = self.channels, self.img_ch, 2 if self.maxout else 1
        wpp, post = self.windows_per_pixel(), 'maxout' if self.maxout else 'none'
        nodes = [node('conv1', ['image'], m*c, self.dilation[0], post=post, wpp=wpp, bias=True)]
        for i in range(self.depth-2):
            nodes.append(node(f'conv{i+2}', [f'conv{i+1}'], m*c, self.dilation[i+1], post=post, wpp=wpp))
        nodes.append(node(f'conv{self.depth}', [f'conv{self.depth-1}'] + (['image'] if self.skip else []),
                          2 if self.residual else g, self.dilation[-1], wpp=wpp, bias=True))
        return dict(img_ch=g, unshuffle=self.unshuffle, pad_to=2 if self.unshuffle else 1,
                    residual=self.residual, nodes=nodes)

    def layer_shapes(self):
        """(name, K, COUT, windows per pixel) per layer. COUT is what the core
        computes: 2C on a maxout layer, of which C go on."""
        return graph_shapes(self.graph())

    def windows_per_pixel(self):
        return 0.25 if self.unshuffle else 1.0

    def receptive_field(self):
        """Width in input pixels that one output pixel depends on."""
        return (1 + 2*sum(self.dilation))*(2 if self.unshuffle else 1)


# ------------------------------------------------------------ layer graphs ---
# A model is a list of nodes run in order. Each node is one core pass: a window
# of kh x kw taps (dilated, strided) over the CONCATENATION of its input maps,
# COUT output channels, bias, ReLU. The host then requantizes the outputs to
# 7-bit codes (one scale per node) and applies the node's post-op:
#   none      the map is the COUT codes
#   maxout    channel c of the map is max(code c, code c + COUT/2)
#   shuffle2  the COUT codes are placed one level up (pixel shuffle), COUT/4
#             channels at twice the height and width; the node's output
#             channels are quantized in groups of four so each map channel
#             keeps one scale
# The image (its 2x2 phases when unshuffle) is the map 'image', scale 1/127.
# Everything but the core pass is host indexing, so a map can feed several
# nodes (a U-Net skip), a node can read several maps (concatenation), and a
# 2x2 stride-2 window is a downsampling that costs 4*C taps, not a layer.
def node(name, inputs, cout, dilation=1, kh=3, kw=3, stride=1, post='none', wpp=1.0, bias=False):
    return dict(name=name, inputs=list(inputs), kh=kh, kw=kw, stride=stride, dilation=int(dilation),
                cout=int(cout), post=post, wpp=float(wpp), bias=bool(bias))


def node_padding(n):
    """Zero padding that keeps the size for odd kernels; none for even (strided) ones."""
    return n['dilation']*(n['kh']//2) if n['kh'] % 2 else 0


def map_channels(spec):
    """Channels of every map: the image, and each node's output after its post-op."""
    ch = {'image': spec['img_ch']}
    for n in spec['nodes']:
        ch[n['name']] = n['cout']//{'none': 1, 'maxout': 2, 'shuffle2': 4}[n['post']]
    return ch


def graph_shapes(spec):
    """(name, K, COUT, windows per pixel) per node; K = kh*kw * input channels."""
    ch = map_channels(spec)
    return [(n['name'], n['kh']*n['kw']*sum(ch[m] for m in n['inputs']), n['cout'], n['wpp'])
            for n in spec['nodes']]


def unet_spec(c1=64, c2=64, enc=3, body=11, dec=2, up_ch=32, dilation=None, maxout_l1=False,
              maxout_l2=False):
    """Two-level U-Net on the unshuffled image. Level 1 is the four 2x2 phases
    (1/4 windows per pixel), level 2 a 2x2 stride-2 window below it (1/16).
    enc 3x3 layers at level 1, a stride-2 node down, body 3x3 layers at level 2,
    an up node whose 4*up_ch outputs are pixel-shuffled to up_ch channels at
    level 1, dec 3x3 layers at level 1 reading [up, last encoder], and an
    output node reading [last decoder, image]. dilation: one value per 3x3
    node in order (enc, body, dec, out)."""
    m1, m2 = 2 if maxout_l1 else 1, 2 if maxout_l2 else 1
    p1, p2 = 'maxout' if maxout_l1 else 'none', 'maxout' if maxout_l2 else 'none'
    n3 = enc + body + dec + 1
    dil = [int(d) for d in (dilation or [1]*n3)]
    assert len(dil) == n3, f'need {n3} dilations (enc {enc} + body {body} + dec {dec} + out), got {len(dil)}'
    d = iter(dil)
    nodes = [node('e1', ['image'], m1*c1, next(d), post=p1, wpp=0.25, bias=True)]
    for i in range(2, enc+1):
        nodes.append(node(f'e{i}', [f'e{i-1}'], m1*c1, next(d), post=p1, wpp=0.25))
    nodes.append(node('down', [f'e{enc}'], c2, 1, kh=2, kw=2, stride=2, wpp=1/16))
    prev = 'down'
    for i in range(1, body+1):
        nodes.append(node(f'b{i}', [prev], m2*c2, next(d), post=p2, wpp=1/16)); prev = f'b{i}'
    nodes.append(node('up', [prev], 4*up_ch, 1, post='shuffle2', wpp=1/16))
    prev = 'up'
    for i in range(1, dec+1):
        nodes.append(node(f'r{i}', [prev] + ([f'e{enc}'] if i == 1 else []), m1*c1, next(d), post=p1,
                          wpp=0.25)); prev = f'r{i}'
    nodes.append(node('out', [prev, 'image'], 4, next(d), wpp=0.25, bias=True))
    return dict(img_ch=4, unshuffle=True, pad_to=4, residual=False, nodes=nodes,
                unet=dict(c1=c1, c2=c2, enc=enc, body=body, dec=dec, up_ch=up_ch, dilation=dil,
                          maxout_l1=maxout_l1, maxout_l2=maxout_l2))


class GraphDenoiser(nn.Module):
    """A float model of any graph: conv per node, BatchNorm on the nodes without
    a bias (as the chain's hidden layers), ReLU everywhere (the core's), the
    post-ops on the host side done in float."""
    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        ch = map_channels(spec)
        self.conv = nn.ModuleDict()
        self.bn = nn.ModuleDict()
        for n in spec['nodes']:
            cin = sum(ch[m] for m in n['inputs'])
            self.conv[n['name']] = nn.Conv2d(cin, n['cout'], (n['kh'], n['kw']), stride=n['stride'],
                                             padding=node_padding(n), dilation=n['dilation'],
                                             bias=n['bias'])
            if not n['bias']:
                self.bn[n['name']] = nn.BatchNorm2d(n['cout'])
        self.residual, self.unshuffle, self.img_ch = spec['residual'], spec['unshuffle'], spec['img_ch']
        assert not self.residual

    def graph(self):
        return self.spec

    def layer_shapes(self):
        return graph_shapes(self.spec)

    def windows_per_pixel(self):
        return min(n['wpp'] for n in self.spec['nodes'])

    def receptive_field(self):
        return 0            # not a chain; the training patch is chosen by hand

    def forward(self, x):
        hh, ww = x.shape[-2:]
        m = self.spec['pad_to']
        if m > 1:
            x = F.pad(x, (0, (-ww) % m, 0, (-hh) % m), mode='replicate')   # = common.pad_mult
        if self.unshuffle:
            x = F.pixel_unshuffle(x, 2)
        maps = {'image': x}
        for n in self.spec['nodes']:
            h = self.conv[n['name']](torch.cat([maps[k] for k in n['inputs']], 1))
            if n['name'] in self.bn:
                h = self.bn[n['name']](h)
            h = F.relu(h)
            maps[n['name']] = post_op(h, n['post'])
        y = maps[self.spec['nodes'][-1]['name']]
        if self.unshuffle:
            y = F.pixel_shuffle(y, 2)
        return y[..., :hh, :ww]


def post_op(h, post):
    """The host side of a node, in float: (B, COUT, h, w) -> the map it stores."""
    if post == 'maxout':
        c = h.shape[1]//2
        return torch.maximum(h[:, :c], h[:, c:])
    if post == 'shuffle2':
        return F.pixel_shuffle(h, 2)
    return h


# --------------------------------------------- the board's arithmetic in float ---
def fold_bn(conv, bn):
    w = conv.weight.detach().double()
    s = bn.weight.detach().double()/torch.sqrt(bn.running_var.detach().double() + bn.eps)
    return w*s.reshape(-1, 1, 1, 1), bn.bias.detach().double() - bn.running_mean.detach().double()*s


def float_layers(net):
    """[(weight (cout,cin,kh,kw), bias (cout,))] per node of the plain conv+ReLU network."""
    if isinstance(net, FoldedQ):
        return [(w.double(), b.double()) for w, b in net.layers()]
    if isinstance(net, GraphDenoiser):
        L = []
        for n in net.spec['nodes']:
            conv = net.conv[n['name']]
            if n['name'] in net.bn:
                L.append(fold_bn(conv, net.bn[n['name']]))
            else:
                L.append((conv.weight.detach().double(), conv.bias.detach().double()))
        return L
    L = [(net.first.weight.detach().double(), net.first.bias.detach().double())]
    L += [fold_bn(c, b) for c, b in zip(net.mid, net.bn)]
    w, b = net.last.weight.detach().double(), net.last.bias.detach().double()
    if getattr(net, 'residual', False):
        w, b = torch.cat([w, -w]), torch.cat([b, -b])       # the sign pair
    L.append((w, b))
    return L


def round_ste(x):
    """round() going forward, the identity going backward."""
    return x + (x.round() - x).detach()


def grad_scale(x, g):
    """x, with its gradient multiplied by g (LSQ, Esser et al. 2020)."""
    return (x - x*g).detach() + x*g


class FoldedQ(nn.Module):
    """A trained model with BatchNorm folded, computed the way the board does.

    Every rule of quantize_denoise.py is reproduced in float with the straight-
    through estimator, so training this module (quantization-aware training)
    trains the integer model the board will run:
      * weights INT8, one symmetric scale max|w|/127 per output channel (per
        group of four on a shuffle2 node), taken from the current weights on
        every forward pass;
      * bias rounded to the accumulator's unit a_main * w_scale;
      * activations 7-bit unsigned, clip(round(x/a), 0, 127)*a, one LEARNABLE
        scale a per node output (LSQ gradient); the image keeps 1/127;
      * a node reading several maps carries the other maps' scale ratios in
        their taps' weights before weight quantization, as quantize() does;
      * the post-op after requantization (max and placement commute with it);
      * the output pixel rounded to 8 bits.
    With quant=False it is the plain folded float network. residual models
    are not supported."""
    def __init__(self, spec, layers, a_out):
        super().__init__()
        assert not spec['residual']
        self.spec = spec
        self.W = nn.ParameterList(nn.Parameter(torch.as_tensor(w).clone().float()) for w, _ in layers)
        self.b = nn.ParameterList(nn.Parameter(torch.as_tensor(b).clone().float()) for _, b in layers)
        nodes = spec['nodes']
        assert len(layers) == len(nodes) and len(a_out) == len(nodes)-1, 'one scale per node but the last'
        self.a = nn.ParameterList(nn.Parameter(torch.tensor(float(v))) for v in a_out)
        self.index = {n['name']: i for i, n in enumerate(nodes)}
        self.ch = map_channels(spec)
        self.quant = True
        self.record = None          # [[tensors]] per node: its output map (calibration)

    def scales(self):
        """Output scale per node but the last."""
        return [v.item() for v in self.a]

    def layers(self):
        return [(w.detach().clone(), b.detach().clone()) for w, b in zip(self.W, self.b)]

    def map_scale(self, name):
        return 1.0/QMAX_A if name == 'image' else self.a[self.index[name]]

    def fq_act(self, x, a):
        if not self.quant:
            return x
        a = grad_scale(a.clamp_min(1e-8), 1.0/math.sqrt(x[0].numel()*QMAX_A))
        return round_ste((x/a).clamp(0, QMAX_A))*a

    def fq_weight(self, W, b, blocks, group=1):
        """blocks: (channels, scale) of each input map, the first the main one."""
        a_main = blocks[0][1]
        if not self.quant:
            return W, b
        cout = W.shape[0]
        parts, start = [], 0
        for k, (n, a) in enumerate(blocks):
            parts.append(W[:, start:start+n] if k == 0 else W[:, start:start+n]*(a/a_main))
            start += n
        Wk = torch.cat(parts, 1)
        s = Wk.reshape(cout, -1).abs().amax(1).clamp_min(1e-12)/QMAX_W
        if group > 1:
            s = s.reshape(-1, group).amax(1).repeat_interleave(group)
        s4 = s.reshape(-1, 1, 1, 1)
        Wq = round_ste(Wk/s4).clamp(QMIN_W, QMAX_W)*s4
        parts, start = [], 0
        for k, (n, a) in enumerate(blocks):
            parts.append(Wq[:, start:start+n] if k == 0 else Wq[:, start:start+n]/(a/a_main))
            start += n
        unit = a_main*s
        return torch.cat(parts, 1), round_ste(b/unit)*unit

    def forward(self, x):
        hh, ww = x.shape[-2:]
        m = self.spec['pad_to']
        if m > 1:
            x = F.pad(x, (0, (-ww) % m, 0, (-hh) % m), mode='replicate')
        if self.spec['unshuffle']:
            x = F.pixel_unshuffle(x, 2)
        maps, nodes = {'image': x}, self.spec['nodes']
        for i, n in enumerate(nodes):
            blocks = [(self.ch[k], self.map_scale(k)) for k in n['inputs']]
            Wq, bq = self.fq_weight(self.W[i], self.b[i], blocks, 4 if n['post'] == 'shuffle2' else 1)
            inp = torch.cat([maps[k] for k in n['inputs']], 1)
            acc = F.relu(F.conv2d(inp, Wq, bq, stride=n['stride'], padding=node_padding(n),
                                  dilation=n['dilation']))
            if i < len(nodes)-1:
                h = post_op(self.fq_act(acc, self.a[i]), n['post'])
                maps[n['name']] = h
                if self.record is not None:
                    self.record[i].append(h.detach())
            else:
                y = round_ste(acc.clamp(0, 1)*255)/255 if self.quant else acc
        if self.spec['unshuffle']:
            y = F.pixel_shuffle(y, 2)
        return y[..., :hh, :ww]


def board_cycles_per_pixel(shapes, p=16, t=4, windows_per_pixel=None):
    """Cycles one output pixel costs the board core (P=16, T=4), dense mode.

    scripts/cifar_budget.py's per-window model, which reproduces every measured
    configuration within 1.3 cycles; on the CIFAR run it read about one cycle
    per window low (289 measured for 288), more on very short windows (32 for
    K=27). Dense mode is the upper bound: sparse mode only shortens the issue
    term, and where the feed floor K dominates it changes nothing.

    Each shape is (name, K, COUT) or (name, K, COUT, windows per pixel); the
    keyword, when given, overrides the latter for every layer.
    """
    tot = 0.0
    for s in shapes:
        _, k, cout = s[:3]
        wpp = windows_per_pixel if windows_per_pixel is not None else (s[3] if len(s) > 3 else 1.0)
        tot += wpp*per_window(k, cout, p, t, dense_per_group(k, t))
    return tot


class Patches:
    """DnCNN's patch source: square crops of the training images at 4 scales.

    40x40 for DnCNN; FFDNet uses 50x50 for grayscale, and an unshuffled model
    needs the larger patch, its receptive field being about 42 pixels wide."""
    def __init__(self, images, patch=40, scales=(1.0, 0.9, 0.8, 0.7)):
        self.patch = patch
        self.pyr = []
        for _, im in images:
            h, w = im.shape
            for s in scales:
                hs, ws = int(h*s), int(w*s)
                if hs < patch or ws < patch:
                    continue            # a 128 px patch does not fit a 180 px image at 0.7
                pil = Image.fromarray(np.uint8(np.rint(im*255))).resize((ws, hs), Image.BICUBIC)
                self.pyr.append(np.asarray(pil, np.float32)/255.0)
        assert self.pyr, f'no training image is {patch} px or larger at any scale'

    def sample(self, n, rng):
        out = np.empty((n, 1, self.patch, self.patch), np.float32)
        p = self.patch
        for i in range(n):
            im = self.pyr[rng.integers(len(self.pyr))]
            y = rng.integers(im.shape[0]-p+1); x = rng.integers(im.shape[1]-p+1)
            a = im[y:y+p, x:x+p]
            m = rng.integers(8)                          # 8 flips/rotations
            a = np.rot90(a, m % 4)
            if m >= 4:
                a = np.flipud(a)
            out[i, 0] = a
        return out


def noisy_batch(clean, sigma, rng):
    n = clean + rng.standard_normal(clean.shape).astype(np.float32)*(sigma/255.0)
    return np.rint(np.clip(n, 0, 1)*QMAX_A).astype(np.float32)/QMAX_A


def evaluate(net, tests):
    net.eval()
    dev = next(net.parameters()).device
    vals = []
    with torch.no_grad():
        for _, clean, noisy in tests:
            out = net(torch.from_numpy(noisy)[None, None].to(dev))[0, 0].cpu().numpy()
            vals.append(psnr(clean, out))
    net.train()
    return float(np.mean(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=7)
    ap.add_argument('--channels', type=int, default=32)
    ap.add_argument('--no-skip', action='store_true', help='no noisy-image input to the last layer')
    ap.add_argument('--residual', action='store_true',
                    help='predict the noise (DnCNN residual learning) through a sign-split last layer')
    ap.add_argument('--unshuffle', action='store_true',
                    help='FFDNet-style: run on the four 2x2 phases at half resolution')
    ap.add_argument('--maxout', action='store_true',
                    help='hidden layers compute 2C maps and keep the larger of each pair')
    ap.add_argument('--dilation', default=None,
                    help='comma separated dilation per layer, e.g. 1,2,3,4,3,2,1 (default all 1)')
    ap.add_argument('--arch', choices=['chain', 'unet'], default='chain')
    ap.add_argument('--unet', default='64,64,3,11,2,32',
                    help='unet: c1,c2,enc,body,dec,up_ch (see unet_spec); --maxout applies to '
                         'level 1, --maxout-l2 to the body; --dilation lists every 3x3 node')
    ap.add_argument('--maxout-l2', action='store_true', help='unet: maxout on the body nodes')
    ap.add_argument('--patch', type=int, default=40, help='training patch size (even)')
    ap.add_argument('--sigma', type=float, default=25)
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--patches', type=int, default=32768, help='random patches per epoch')
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--threads', type=int, default=0, help='torch threads (0 = default)')
    ap.add_argument('--device', default='auto', help="auto (cuda when there is one), cuda or cpu")
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--name', default=None, help='output name (default from the shape)')
    ap.add_argument('--schedule', choices=['cosine', 'plateau'], default='cosine')
    ap.add_argument('--val-every', type=int, default=20,
                    help='plateau: hold out every N-th training image for validation')
    ap.add_argument('--patience', type=int, default=6, help='plateau: epochs before halving the rate')
    ap.add_argument('--stop-patience', type=int, default=15, help='plateau: epochs before stopping')
    ap.add_argument('--min-lr', type=float, default=2e-5, help='plateau: stop below this rate')
    ap.add_argument('--resume', action='store_true',
                    help='continue <name>: exactly from <name>_last.pt when it exists, otherwise '
                         'from the best checkpoint <name>.pt with a fresh optimizer at --lr')
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    dev = ('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
    dil = [int(v) for v in args.dilation.split(',')] if args.dilation else None
    if args.arch == 'unet':
        c1, c2, enc, body, dec, up_ch = [int(v) for v in args.unet.split(',')]
        spec = unet_spec(c1, c2, enc, body, dec, up_ch, dil, args.maxout, args.maxout_l2)
        net = GraphDenoiser(spec).to(dev)
        name = args.name or (f'unet_c{c1}_{c2}_e{enc}b{body}d{dec}_u{up_ch}' +
                             ('_dil' if max(spec['unet']['dilation']) > 1 else '') +
                             ('_mo' if args.maxout else '') + ('_mo2' if args.maxout_l2 else ''))
    else:
        net = Denoiser(args.depth, args.channels, not args.no_skip, args.residual,
                       args.unshuffle, dil, args.maxout).to(dev)
        name = args.name or (f'dn_d{args.depth}_c{args.channels}' + ('_us' if net.unshuffle else '') +
                             ('_dil' if max(net.dilation) > 1 else '') + ('_mo' if net.maxout else '') +
                             ('_res' if net.residual else ('' if net.skip else '_noskip')))
    print(f'device: {dev}')
    shapes = net.layer_shapes()
    for n, k, c, _ in shapes:
        assert k <= K_MAX and c <= COUT_MAX, f'{n}: K={k} COUT={c} exceeds the board build'
    cpp = board_cycles_per_pixel(shapes)
    rf = net.receptive_field()
    print(f'{name}: {sum(p.numel() for p in net.parameters()):,} parameters, '
          f'layers {[(nm, k, c) for nm, k, c, _ in shapes]}, '
          + (f'dilation {net.dilation}, receptive field {rf}x{rf}' if rf else
             f'dilation {net.spec["unet"]["dilation"]}'))
    print(f'board cost {cpp:.0f} cycles/pixel -> 256x256 at 50 MHz: {cpp*65536/50e6:.2f} s')

    train_imgs = load_set('Train400')
    val = None
    if args.schedule == 'plateau':
        held = set(range(0, len(train_imgs), args.val_every))
        val = test_noise([im for i, im in enumerate(train_imgs) if i in held], args.sigma, seed=1)
        train_imgs = [im for i, im in enumerate(train_imgs) if i not in held]
        print(f'validation: {len(val)} training images held out, {len(train_imgs)} left to train on')
    patches = Patches(train_imgs, patch=args.patch)
    tests = test_noise(load_set('Set12'), args.sigma, seed=0)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    if args.schedule == 'cosine':
        # DnCNN steps the rate down late in training; cosine does the same smoothly.
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr/20)
    else:
        sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='max', factor=0.5,
                                                           patience=args.patience)
    best_val, best_ep, stale = -1.0, 0, 0
    curve, start_ep, resumed = [], 1, None

    # Everything needed to continue exactly where training stopped, written every
    # epoch: the container this runs in can restart, and the best checkpoint
    # alone loses the optimizer, the schedule and the random state.
    last = HERE/f'{name}_last.pt'
    if args.resume:
        if last.exists():
            st = torch.load(last, map_location='cpu', weights_only=False)
            net.load_state_dict(st['state']); opt.load_state_dict(st['opt'])
            sched.load_state_dict(st['sched'])
            rng.bit_generator.state = st['np_rng']; torch.set_rng_state(st['torch_rng'])
            best_val, best_ep, stale, curve = st['best_val'], st['best_ep'], st['stale'], st['curve']
            start_ep = st['epoch'] + 1
            resumed = dict(kind='exact', from_epoch=st['epoch'])
        else:
            ck = torch.load(HERE/f'{name}.pt', map_location='cpu', weights_only=False)
            net.load_state_dict(ck['state'])
            for g in opt.param_groups:
                g['lr'] = args.lr
            best_val, best_ep = ck.get('val_psnr', -1.0), ck['epoch']
            start_ep = ck['epoch'] + 1
            # A different stream from the first run's, so its patches are not replayed.
            rng = np.random.default_rng([args.seed, start_ep])
            resumed = dict(kind='from_best', from_epoch=ck['epoch'],
                           note='optimizer, schedule and random state were not saved by the '
                                'interrupted run; continued from its best checkpoint with a '
                                'fresh Adam at --lr')
        print(f'resuming {name} at epoch {start_ep} ({resumed["kind"]}), best validation '
              f'{best_val:.3f} dB at epoch {best_ep}, lr {opt.param_groups[0]["lr"]:.1e}')

    def write_json():
        (HERE/f'{name}_train.json').write_text(json.dumps(dict(
            name=name, args=vars(args), layers=shapes, board_cycles_per_pixel=cpp,
            best_val_epoch=best_ep if val is not None else None, resumed=resumed,
            curve=curve), indent=2), encoding='utf-8')

    t0 = time.time()
    for ep in range(start_ep, args.epochs+1):
        clean = patches.sample(args.patches, rng)
        noisy = noisy_batch(clean, args.sigma, rng)
        order = rng.permutation(args.patches)
        tot = 0.0
        for i in range(0, args.patches, args.batch):
            idx = order[i:i+args.batch]
            x = torch.from_numpy(noisy[idx]).to(dev); y = torch.from_numpy(clean[idx]).to(dev)
            loss = F.mse_loss(net(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()*len(idx)
        t12 = evaluate(net, tests)
        rec = dict(epoch=ep, loss=tot/args.patches, set12_psnr=t12, lr=opt.param_groups[0]['lr'],
                   seconds=round(time.time()-t0, 1))
        ckpt = dict(state=net.state_dict(), arch=args.arch, graph=net.graph(), depth=args.depth,
                    channels=args.channels, sigma=args.sigma, epoch=ep, set12_psnr=t12,
                    **(dict(skip=net.skip, residual=net.residual, unshuffle=net.unshuffle,
                            dilation=net.dilation, maxout=net.maxout) if args.arch == 'chain'
                       else dict(skip=True, residual=False, unshuffle=True, maxout=args.maxout,
                                 dilation=net.spec['unet']['dilation'], unet=net.spec['unet'])))
        if val is None:
            sched.step()
            torch.save(ckpt, HERE/f'{name}.pt')
            msg = ''
        else:
            v = evaluate(net, val)
            rec['val_psnr'] = v
            ckpt['val_psnr'] = v
            sched.step(v)
            if v > best_val:
                best_val, best_ep, stale = v, ep, 0
                torch.save(ckpt, HERE/f'{name}.pt')      # the best on validation
            else:
                stale += 1
            msg = f'val {v:.3f} dB (best {best_val:.3f} @ {best_ep})  lr {rec["lr"]:.1e}  '
        curve.append(rec)
        torch.save(dict(state=net.state_dict(), opt=opt.state_dict(), sched=sched.state_dict(),
                        np_rng=rng.bit_generator.state, torch_rng=torch.get_rng_state(),
                        epoch=ep, best_val=best_val, best_ep=best_ep, stale=stale, curve=curve),
                   last)
        write_json()
        print(f'epoch {ep:>3}/{args.epochs}  loss {tot/args.patches:.6f}  {msg}'
              f'Set12 {t12:.2f} dB (test, not used)  {time.time()-t0:7.0f}s', flush=True)
        if val is not None and (stale >= args.stop_patience or
                                opt.param_groups[0]['lr'] < args.min_lr):
            print(f'early stop at epoch {ep}: best validation {best_val:.3f} dB at epoch {best_ep}')
            break
    write_json()
    print(f'wrote {HERE/(name + ".pt")}')


if __name__ == '__main__':
    main()
