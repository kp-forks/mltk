
import sys
import os
from typing import TYPE_CHECKING

__version__ = '0.20.0'

MLTK_DIR = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
MLTK_ROOT_DIR = os.path.dirname(MLTK_DIR).replace('\\', '/')


def disable_tensorflow():
    """Disable the Tensorflow Python package with a placeholder

    Tensorflow is very bloaty
    If we can get away without importing it we can save a lot of time
    and potentially diskspace if we remove it as a dependency

    This also disables matplotlib which can also be bloaty
    """
    sys.path.insert(0, f'{MLTK_DIR}/core/keras/tensorflow_placeholder')


if os.environ.get('MLTK_DISABLE_TF', '0') == '1' or TYPE_CHECKING:
    disable_tensorflow()
if 'TF_USE_LEGACY_KERAS' not in os.environ:
    # The MTLK is currently based on the "legacy" keras, i.e. the keras that is inside the TF package
    # e.g.  import tensorflow.keras
    os.environ['TF_USE_LEGACY_KERAS'] = '1'
