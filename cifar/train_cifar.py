"""Train the small CIFAR-10 CNN that the accelerator can actually run.

Two hardware facts shape this network, and the script checks both rather than
leaving them to be discovered on the board:

  * Activations reach the core on a 7-bit port, so every value it is fed must
    land in 0..127 -- unsigned. That rules out mean/std normalisation, whose
    output is signed. The images go in as [0,1] and the first BatchNorm learns
    whatever scaling the network wants, which costs nothing in accuracy.

  * The core always applies ReLU, so it cannot produce logits. Global average
    pooling and the 128x10 classifier stay on the host; together they are 1,280
    multiplies against the convolutions' 38.6 million, so nothing meaningful
    moves off the accelerator.

BatchNorm is used for training and folded into the convolution weights at
quantisation time, so the deployed network is plain conv + bias + ReLU.

    python cifar/train_cifar.py --epochs 60
    python cifar/train_cifar.py --epochs 2 --limit 2000   # a quick smoke run

Writes cifar/cifar_cnn.pt. Expect roughly 90% test accuracy at 60 epochs; a
couple of epochs is enough to prove the flow end to end before committing hours
to it.
"""
import argparse
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

HERE = Path(__file__).resolve().parent

# (in, out) per conv, with a maxpool after every pair. Kept here so the
# quantiser and the export read the same definition.
CONVS = [(3, 32), (32, 32), (32, 64), (64, 64), (64, 128), (128, 128)]
CLASSES = 10

# What the built core must provide. Checked below against the layer shapes.
K_MAX, COUT_MAX = 1152, 128


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.ModuleList(nn.Conv2d(i, o, 3, padding=1, bias=False)
                                  for i, o in CONVS)
        self.bn = nn.ModuleList(nn.BatchNorm2d(o) for _, o in CONVS)
        self.fc = nn.Linear(CONVS[-1][1], CLASSES)

    def forward(self, x):
        for i, (c, b) in enumerate(zip(self.conv, self.bn)):
            x = F.relu(b(c(x)))
            if i % 2 == 1:
                x = F.max_pool2d(x, 2)
        return self.fc(x.mean((2, 3)))      # global average pool, then classify


def check_fits():
    """Refuse to train a network the core cannot be configured to run."""
    worst = 0
    for cin, cout in CONVS:
        k = cin*9
        assert k <= K_MAX, f'conv {cin}->{cout} needs K={k}, core provides {K_MAX}'
        assert cout <= COUT_MAX, f'conv {cin}->{cout} exceeds COUT_MAX={COUT_MAX}'
        worst = max(worst, 127*k*127)
    assert worst <= 2**31-1, f'accumulator could overflow INT32: {worst}'
    print(f'shapes fit: K_MAX={K_MAX}, COUT_MAX={COUT_MAX}, '
          f'worst accumulator {worst:,} < {2**31-1:,}')


def loaders(batch, workers, limit):
    # ToTensor alone gives [0,1]. No Normalize: the core's input port is
    # unsigned, and a signed input could not be fed to it.
    tr = transforms.Compose([transforms.RandomCrop(32, padding=4),
                             transforms.RandomHorizontalFlip(),
                             transforms.ToTensor()])
    te = transforms.ToTensor()
    root = HERE/'data'
    a = datasets.CIFAR10(root, train=True, download=True, transform=tr)
    b = datasets.CIFAR10(root, train=False, download=True, transform=te)
    if limit:
        a, b = Subset(a, range(limit)), Subset(b, range(min(limit, len(b))))
    return (DataLoader(a, batch, shuffle=True, num_workers=workers, drop_last=True),
            DataLoader(b, 512, shuffle=False, num_workers=workers))


@torch.no_grad()
def accuracy(net, dl, dev):
    net.eval()
    ok = n = 0
    for x, y in dl:
        p = net(x.to(dev)).argmax(1).cpu()
        ok += (p == y).sum().item(); n += y.numel()
    return ok/max(n, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=60)
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--lr', type=float, default=0.1)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--limit', type=int, default=0, help='images per split, for a smoke run')
    ap.add_argument('--out', type=Path, default=HERE/'cifar_cnn.pt')
    args = ap.parse_args()

    check_fits()
    if args.limit and args.limit < args.batch:
        raise SystemExit(f'--limit {args.limit} is below --batch {args.batch}; with '
                         f'drop_last there would be no batches at all')
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'device: {dev}'
          + ('   (CPU training is slow -- try --epochs 2 --limit 2000 first)'
             if dev == 'cpu' else ''))

    train, test = loaders(args.batch, args.workers, args.limit)
    net = Net().to(dev)
    opt = torch.optim.SGD(net.parameters(), lr=args.lr, momentum=0.9,
                          weight_decay=5e-4, nesterov=True)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, args.lr, epochs=args.epochs, steps_per_epoch=len(train))

    best = 0.0
    for ep in range(args.epochs):
        net.train(); t0 = time.time(); tot = 0.0
        for x, y in train:
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(net(x), y)
            loss.backward(); opt.step(); sched.step()
            tot += loss.item()
        acc = accuracy(net, test, dev)
        flag = ''
        if acc > best:
            best = acc
            torch.save({'state': net.state_dict(), 'convs': CONVS,
                        'classes': CLASSES, 'acc': acc}, args.out)
            flag = '  <- saved'
        print(f'epoch {ep+1:3d}/{args.epochs}  loss {tot/len(train):.4f}  '
              f'test {acc*100:5.2f}%  {time.time()-t0:5.1f}s{flag}')

    print(f'\nbest test accuracy {best*100:.2f}%, written to {args.out}')
    print('next: python cifar/quantize_cifar.py')


if __name__ == '__main__':
    main()
