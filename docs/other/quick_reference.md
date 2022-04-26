# Quick Reference

The following provides a brief description of some of the more common concepts used by the MLTK.


## File Types

###  .tflite: Tensorflow-Lite Model

File extension:  `.tflite`

This is generated by the Tensorflow-Lite [converter](https://www.tensorflow.org/lite/convert) and loaded by the Tensorflow-Lite Micro [interpreter](https://github.com/tensorflow/tflite-micro). This is a binary file that can be directly programmed into an embedded device.

This file is based on the [flatbuffer](https://google.github.io/flatbuffers) schema defined by Tensorflow-Lite, [schema.fbs](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/schema/schema.fbs).  
You may view the contents of this file by dragging and dropping into the webpage: [https://netron.app](https://netron.app).

### .h5: Keras Model

File extension: `.h5`

This is [generated](https://keras.io/api/models/model_saving_apis/#save_model-function) by Keras after model training completes. This typically contains float32 weights. The TF-Lite converter uses this to generate a quantize `.tflite` file

You may view the contents of this file by dragging and dropping into the webpage: [https://netron.app](https://netron.app).


### .mltk.zip: MLTK Model Archive

File extension: `.mltk.zip`

This contains the model specification, trained model files (`.tflite`, `.h5`), training logs, and evaluate logs.  
See [Model Archive](../guides/model_archive.md) for more details.

### .py: Model Specification

File extension: `.py`

This defines the model structure, the training dataset including any augmentations, the training parameters, and any additional model parameters.  
See [Model Specification](../guides/model_specification.md) for more details.


## Model Object Types

The following model Python objects are used by the MLTK:

### MltkModel

The [MltkModel](mltk.core.MltkModel) contains all information required to train a model.


### TfliteModel

The [TfliteModel](mltk.core.TfliteModel) loads a `.tflite` model file and provides programmic access to it contents.

### KerasModel

The [KerasModel](mltk.core.KerasModel) is what is trained by Tensorflow. This defines the actual model layout.