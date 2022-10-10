# Tensorflow-Lite Model

This allows for accessing [.tflite](https://www.tensorflow.org/lite/models/convert) model files.
A `.tflite` uses a binary format called a [flatbuffer](https://google.github.io/flatbuffers/). 
The flatbuffer "schema" used by a `.tflite` model is defined in [schema.fbs](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/schema/schema.fbs).


Example usage of this package is as follows:

```python
# Import the TfliteModel class
from mltk.core import TfliteModel 

# Load the .tflite
tflite_model = TfliteModel.load_flatbuffer_file(tflite_path)

# Generate a summary of the .tflite
summary = tflite_model.summary()

# Print the summary to the console
print(summary)
```

See the [TfliteModel API examples](https://siliconlabs.github.io/mltk/mltk/examples/tflite_model.html) for more examples.



```{eval-rst}
.. autosummary::
   :toctree: model
   :template: custom-class-template.rst

   mltk.core.TfliteModel

.. autosummary::
   :toctree: layer
   :template: custom-class-template.rst

   mltk.core.TfliteLayer

.. autosummary::
   :toctree: add_layer
   :template: custom-class-template.rst

   mltk.core.TfliteAddLayer

.. autosummary::
   :toctree: conv2d_layer
   :template: custom-class-template.rst

   mltk.core.TfliteConv2dLayer

.. autosummary::
   :toctree: fully_connected_layer
   :template: custom-class-template.rst

   mltk.core.TfliteFullyConnectedLayer

.. autosummary::
   :toctree: depthwise_conv2d_layer
   :template: custom-class-template.rst

   mltk.core.TfliteDepthwiseConv2dLayer

.. autosummary::
   :toctree: pooling2d_layer
   :template: custom-class-template.rst

   mltk.core.TflitePooling2dLayer

.. autosummary::
   :toctree: reshape_layer
   :template: custom-class-template.rst

   mltk.core.TfliteReshapeLayer

.. autosummary::
   :toctree: quantize_layer
   :template: custom-class-template.rst

   mltk.core.TfliteQuantizeLayer

.. autosummary::
   :toctree: dequantize_layer
   :template: custom-class-template.rst

   mltk.core.TfliteDequantizeLayer

.. autosummary::
   :toctree: tensor
   :template: custom-class-template.rst

   mltk.core.TfliteTensor

.. autosummary::
   :toctree: shape
   :template: custom-class-template.rst

   mltk.core.TfliteShape


.. autosummary::
   :toctree: quantization
   :template: custom-class-template.rst

   mltk.core.TfliteQuantization

.. autosummary::
   :toctree: parameters
   :template: custom-class-template.rst

   mltk.core.TfliteModelParameters
```


```{toctree}
:maxdepth: 1
:hidden:

./model
./parameters
./dictionary.fbs.md
./layer
./add_layer
./conv2d_layer
./fully_connected_layer
./depthwise_conv2d_layer
./pooling2d_layer
./reshape_layer
./quantize_layer
./dequantize_layer
./tensor
./shape
./quantization
```