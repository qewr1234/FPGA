"""Compare the npz (from the Hugging Face parquet) with the official CIFAR-10 test_batch, image by image.

    python -I verify_official.py TARBALL EXTRACT_DIR TEST_NPZ
The tarball's MD5 is checked against torchvision's constant before anything in it is unpickled.
"""
import hashlib
import json
import pickle
import sys
import tarfile
from pathlib import Path

import numpy as np

TGZ_MD5 = 'c58f30108f718f92721af3b95e74349a'          # torchvision.datasets.CIFAR10.tgz_md5
TEST_MD5 = '40351d587109b95175f43aff81a1287e'         # torchvision.datasets.CIFAR10.test_list
tgz, out, npz = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
md5 = hashlib.md5(tgz.read_bytes()).hexdigest()
assert md5 == TGZ_MD5, md5
with tarfile.open(tgz) as t:
    member = t.getmember('cifar-10-batches-py/test_batch')
    t.extract(member, out, filter='data')
batch = out/'cifar-10-batches-py'/'test_batch'
assert hashlib.md5(batch.read_bytes()).hexdigest() == TEST_MD5
with open(batch, 'rb') as fh:
    d = pickle.load(fh, encoding='bytes')
off = d[b'data'].reshape(-1, 3, 32, 32)
lab = np.asarray(d[b'labels'], np.int64)
z = np.load(npz)
print(json.dumps(dict(tgz_md5=md5, test_batch_md5=TEST_MD5,
                      test_batch_sha256=hashlib.sha256(batch.read_bytes()).hexdigest(),
                      images_identical=bool(np.array_equal(off, z['images'])),
                      labels_identical=bool(np.array_equal(lab, z['labels'])), n=int(len(lab)))))
