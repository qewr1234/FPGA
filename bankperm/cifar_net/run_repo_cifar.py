"""Run the repository's cifar/train_cifar.py or cifar/quantize_cifar.py unchanged, with torchvision's
CIFAR10 replaced by the same images read from npz (converted from the Hugging Face parquet of
uoft-cs/cifar10, so no pickle from the download is loaded).

    python run_repo_cifar.py NPZ_DIR train    --epochs 12 --out CKPT ...
    python run_repo_cifar.py NPZ_DIR quantize --ckpt CKPT --out EXPORT ...
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'cifar'))
npz_dir, which, rest = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]


class NpzCIFAR10:
    """torchvision.datasets.CIFAR10's interface: PIL image through transform, int label."""

    def __init__(self, root, train=True, download=False, transform=None):
        d = np.load(npz_dir/('train.npz' if train else 'test.npz'))
        self.data = np.ascontiguousarray(d['images'].transpose(0, 2, 3, 1))     # HWC, as torchvision
        self.targets = d['labels'].tolist()
        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        img = Image.fromarray(self.data[i])
        if self.transform is not None:
            img = self.transform(img)
        return img, self.targets[i]


import torch  # noqa: E402
import train_cifar  # noqa: E402
train_cifar.datasets.CIFAR10 = NpzCIFAR10


class NetCL(train_cifar.Net):
    """The repository's Net, computed in channels_last (7x faster on this CPU; same parameters,
    same state_dict keys and values -- only the memory layout of the tensors differs)."""

    def __init__(self):
        super().__init__()
        self.to(memory_format=torch.channels_last)

    def forward(self, x):
        return super().forward(x.contiguous(memory_format=torch.channels_last))


if which == 'train':
    train_cifar.Net = NetCL
    sys.argv = ['train_cifar.py'] + rest
    train_cifar.main()
elif which == 'quantize':
    import quantize_cifar  # noqa: E402
    quantize_cifar.datasets.CIFAR10 = NpzCIFAR10
    sys.argv = ['quantize_cifar.py'] + rest
    quantize_cifar.main()
else:
    raise SystemExit(which)
