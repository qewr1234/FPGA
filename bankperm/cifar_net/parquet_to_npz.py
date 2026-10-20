"""CIFAR-10 parquet (Hugging Face uoft-cs/cifar10, PNG bytes) -> npz of uint8 (N, 3, 32, 32) + labels."""
import io
import sys

import numpy as np
import pyarrow.parquet as pq
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
t = pq.read_table(src).to_pydict()
keys = list(t)
img_key = next(k for k in keys if 'im' in k)
lab_key = next(k for k in keys if 'label' in k)
imgs = np.stack([np.asarray(Image.open(io.BytesIO(d['bytes'])).convert('RGB'), np.uint8) for d in t[img_key]])
labels = np.asarray(t[lab_key], np.int64)
assert imgs.shape[1:] == (32, 32, 3), imgs.shape
np.savez(dst, images=imgs.transpose(0, 3, 1, 2).copy(), labels=labels)
print(dst, imgs.shape, np.bincount(labels))
