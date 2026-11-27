# SPDX-License-Identifier: GPL-3.0-or-later
"""sluice: a virtual audio mixer for PipeWire."""

import os as _os

__version__ = "0.12.6"

# 0.11.7: the maths libraries numpy and scipy load start one worker thread per processor thread (32 on a 16-core Ryzen), and Sluice
# never gives them work big enough to share. One each is enough; set before numpy is imported. A value you set yourself is kept.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_name, "1")
del _name
