
import os
import sysconfig
import logging
import importlib
import copy
import threading
import inspect
import functools
from typing import Union, List, Dict, Tuple, Callable
import numpy as np

from mltk.core.tflite_model import TfliteModel, TfliteLayer
from mltk.core.utils import get_mltk_logger
from mltk.utils.python import (as_list, get_case_insensitive, import_module_at_path, append_exception_msg)
from mltk.utils.path import (fullpath, get_user_setting)
from .tflite_micro_accelerator import (TfliteMicroAccelerator, PlaceholderTfliteMicroAccelerator)
from .tflite_micro_model import TfliteMicroModel, TfliteMicroModelDetails



class TfliteMicro:
    """This class wraps the TF-Lite Micro C++ library

    This class allows for loading a .tflite model file
    into the TF-Lite Micro (TFLM) C++ library and running inference
    using either the TFLM reference kernels or hardware accelerated kernels.
    """
    _model_lock = threading.Lock()
    _wrapper = None
    _logger:logging.Logger = None
    _logged_errors:List[str] = []
    _accelerators:Dict[str,TfliteMicroAccelerator] = {}
    _accelerator_paths:List[str] = []

    @staticmethod
    def git_hash() -> str:
        """Return the GIT hash of the MLTK repo used to compile the wrapper library"""
        wrapper = TfliteMicro._load_wrapper()
        return wrapper.git_hash()

    @staticmethod
    def api_version() -> int:
        """Return the TFLM API version number.
        This is used to ensure accelerator wrappers are compatible with
        this TFLM wrapper"""
        wrapper = TfliteMicro._load_wrapper()
        return wrapper.api_version()

    @staticmethod
    def set_log_level(level: str) -> str:
        """Set the C++ wrapper logging level

        NOTE: This sets the level in the C++ wrapper, NOT the Python logger.
            Increasing the logging level can help with throughput as each
            log generated by the wrapper needs to be forwarded to the Python logger.

        Returns:
            The previous log level
        """
        wrapper = TfliteMicro._load_wrapper()
        prev_level = wrapper.get_log_level()
        if not wrapper.set_log_level(level):
            raise RuntimeError(f'Failed to set MLTK log level to {level}')
        return prev_level

    @staticmethod
    def get_log_level() -> str:
        """Return the C++ wrapper's logging level

        NOTE: This returns the C++ wrapper's logging level, NOT the Python logger.
        """
        wrapper = TfliteMicro._load_wrapper()
        return wrapper.get_log_level()

    @staticmethod
    def set_logger(logger: logging.Logger):
        """Set the wrapper's Python logger

        This logger will be invoked by the C++ wrapper's logging callback.
        """
        TfliteMicro._logger = logger

    @staticmethod
    def get_logger() -> logging.Logger:
        """Return the wrapper's Python logger"""
        # Just use the MLTK logger if no logger has been specified
        if TfliteMicro._logger is None:
            logger = get_mltk_logger()
            TfliteMicro._logger = logger

        return TfliteMicro._logger

    @staticmethod
    def normalize_accelerator_name(accelerator:str) -> str:
        """Given a case-insensitive accelerator name, normalize
        the name to the format used by the C++ library

        Returns:
            Normalized name of accelerator or None if accelerator
            is unknown
        """
        TfliteMicro._load_wrapper()
        if accelerator is None:
            return None

        return get_case_insensitive(accelerator, TfliteMicro._accelerators)

    @staticmethod
    def get_supported_accelerators() -> List[str]:
        """Return a list of supported accelerators by name"""
        TfliteMicro._load_wrapper()
        return [x for x in TfliteMicro._accelerators]

    @staticmethod
    def accelerator_is_supported(accelerator:str) -> bool:
        """Return if the given accelerator is supported"""
        TfliteMicro._load_wrapper()
        return get_case_insensitive(accelerator, TfliteMicro._accelerators) is not None


    @staticmethod
    def load_tflite_model(
        model: Union[str, TfliteModel],
        accelerator:str=None,
        enable_profiler=False,
        enable_recorder=False,
        enable_tensor_recorder=False,
        force_buffer_overlap=False,
        runtime_buffer_size:int=None,
        **kwargs
    ) -> TfliteMicroModel:
        """Load the TF-Lite Micro interpreter with the given .tflite model

        NOTE:
        - Only 1 model may be loaded at a time
        - You must call unload_model() when the model is no longer needed

        """
        wrapper = TfliteMicro._load_wrapper()

        if accelerator is not None:
            tflm_accelerator = TfliteMicro.get_accelerator(accelerator)
            if hasattr(tflm_accelerator, 'init_variant'):
                tflm_accelerator.init_variant()
        else:
            tflm_accelerator = None

        TfliteMicro._model_lock.acquire()

        try:
            tflite_model = _load_tflite_model(model)
            runtime_buffer_sizes = _retrieve_runtime_buffer_sizes(
                tflite_model,
                runtime_buffer_size=runtime_buffer_size,
                accelerator=accelerator
            )
            tflm_model = TfliteMicroModel(
                tflm_wrapper=wrapper,
                tflm_accelerator=tflm_accelerator,
                flatbuffer_data=tflite_model.flatbuffer_data,
                enable_profiler=enable_profiler,
                enable_recorder=enable_recorder,
                enable_tensor_recorder=enable_tensor_recorder,
                force_buffer_overlap=force_buffer_overlap,
                runtime_buffer_sizes=runtime_buffer_sizes,
            )
        except:
            # Release the model lock if an exception occurred while loading it
            TfliteMicro._model_lock.release()
            raise

        return tflm_model

    @staticmethod
    def unload_model(model: TfliteMicroModel):
        """Unload a previously loaded model"""
        accelerator = model.accelerator
        if accelerator is not None:
            if hasattr(accelerator, 'deinit_variant'):
                accelerator.deinit_variant()

        # pylint: disable=protected-access
        if model._model_wrapper:
            model._model_wrapper.unload()
        del model
        TfliteMicro._model_lock.release()



    @staticmethod
    def profile_model(
        model: Union[str, TfliteModel],
        accelerator:str=None,
        return_estimates=False,
        disable_simulator_backend=False,
        runtime_buffer_size=-1, # If runtime_buffer_size not given, determine the optimal memory size
        input_data: Union[np.ndarray,List[np.ndarray]]=None,
        **kwargs
    ): # -> ProfilingModelResults
        """Profile the given model in the simulator and optionally determine metric estimates

        """
        from mltk.core.profiling_results import ProfilingModelResults, ProfilingLayerResult

        tflite_model = _load_tflite_model(model)
        tflm_model = TfliteMicro.load_tflite_model(
            model=tflite_model,
            accelerator=accelerator,
            enable_profiler=True,
            enable_recorder=True,
            runtime_buffer_size=runtime_buffer_size
        )
        try:
            renable_simulator_backend = False
            disable_calculate_accelerator_cycles_only = False
            tflm_accelerator = tflm_model.accelerator

            if disable_simulator_backend and \
                tflm_accelerator is not None and \
                hasattr(tflm_accelerator, 'set_simulator_backend_enabled'):
                renable_simulator_backend = True
                tflm_accelerator.set_simulator_backend_enabled(False)

            if hasattr(tflm_accelerator, 'set_calculate_accelerator_cycles_only_enabled'):
                # For profiling, we only need the accelerator cycles
                # The simulator does not need to actually calculate valid output data
                # This greatly improves simulation latency
                disable_calculate_accelerator_cycles_only = True
                tflm_accelerator.set_calculate_accelerator_cycles_only_enabled(True)

            tflm_model_details = tflm_model.details

            if input_data is not None:
                if isinstance(input_data, list):
                    for i, v in enumerate(input_data):
                        tflm_model.input(index=i, value=v)
                else:
                    tflm_model.input(value=input_data)
            else:
                for i in range(tflm_model.input_size):
                    input_tensor = tflm_model.input(i)
                    empty_tensor = np.zeros_like(input_tensor)
                    tflm_model.input(i, value=empty_tensor)

            tflm_model.invoke()
            tflm_results = tflm_model.get_profiling_results()
            recorded_data = tflm_model.get_recorded_data()

            if renable_simulator_backend:
                tflm_accelerator.set_simulator_backend_enabled(True)
            if disable_calculate_accelerator_cycles_only:
                tflm_accelerator.set_calculate_accelerator_cycles_only_enabled(False)

            recorded_layers = recorded_data['layers']
            layer_results = []
            for layer_index, tflm_layer_result in enumerate(tflm_results):
                tflite_layer = tflite_model.layers[layer_index]
                layer_err = tflm_model.get_layer_error(layer_index)
                layer_err_msg = None if layer_err is None else layer_err.msg
                del tflm_layer_result['name']
                layer_result = ProfilingLayerResult(
                    tflite_layer=tflite_layer,
                    error_msg=layer_err_msg,
                    **tflm_layer_result
                )

                layer_recorded_data = recorded_layers[layer_index] if layer_index < len(recorded_layers) else {}
                updated = True 
                while updated:
                    updated = False
                    for key, value in layer_recorded_data.items():
                        if not isinstance(value, (int,float,str)):
                            tflite_layer.metadata[key] = value
                            layer_recorded_data.pop(key)
                            updated = True 
                            break 

                layer_result.update(layer_recorded_data)
                layer_results.append(layer_result)

        finally:
            TfliteMicro.unload_model(tflm_model)

        model_details = tflm_model.details
        _add_memory_plan(
            tflite_model=tflite_model,
            recorded_data=recorded_data,
            model_details=model_details
        )

        results = ProfilingModelResults(
            model=tflite_model,
            accelerator=accelerator,
            runtime_memory_bytes=tflm_model_details.runtime_memory_size,
            layers=layer_results,
            model_details=model_details
        )

        # If we want to return estimates for metrics like:
        # CPU cycles and energy
        if return_estimates:
            # If accelerator=none
            # then just use the MVP accelerator's 'none' (i.e. CMSIS-only) estimators
            if tflm_accelerator is None and 'mvp' in TfliteMicro._accelerators:
                tflm_accelerator = TfliteMicro._accelerators['mvp']

            if tflm_accelerator is not None:
                tflm_accelerator.estimate_profiling_results(
                    results=results,
                    **kwargs
                )

        return results


    @staticmethod
    def record_model(
        model: Union[str, TfliteModel],
        input_data: Union[np.ndarray,List[np.ndarray]]=None,
        accelerator:str=None,
        enable_accelerator_recorder=False,
        disable_simulator_backend=False,
        enable_tensor_recorder=True,
        return_model_details=False,
        update_input_model=False,
        layer_callback:Callable[[TfliteLayer], bool]=None,
    ) -> Union[List[TfliteLayer], Tuple[List[TfliteLayer],TfliteMicroModelDetails]]:
        """Run one inference and record each model layer's input/output tensors

        Args:
            model: path to .tflite model file or TfliteModel instance
            input_data: Model input0 data as numpy array or list of numpy arrays for each model input
            accelerator: Optional accelerator to use for inference
            enable_accelerator_recorder: If enabled, record the data/instructions generated by the hardware accelerator
                The recorded data with be stored in each layers' metadata property, .e.g.: ``layer.metadata['accelerator_data']``.
                Each layers' recorded data is a dictionary with the entries specific to the hardware accelerator.
            disable_simulator_backend: Disable the simulator backend while running the accelerator recorder.
                This can greatly improve execution time, however, the generated data output (i.e. output tensors) is invalid
            enable_tensor_recorder: Record the input/output tensors of each layer
            return_model_details: Also return the recorded model's TfliteMicroModelDetails
        Return:
            If return_model_details=False, then return a list of TfliteLayers with the tensor data
            updated with the recorded values from the previous inference
            If return_model_details=True, then return a tuple(list(TfliteLayers), TfliteMicroModelDetails)
        """
        if update_input_model and not isinstance(model, TfliteModel):
            raise ValueError('Input model must be a TfliteModel instance to use update_input_model=True')

        tflite_model = _load_tflite_model(model)
        tflm_model = TfliteMicro.load_tflite_model(
            model=tflite_model,
            accelerator=accelerator,
            enable_recorder=True,
            enable_tensor_recorder=enable_tensor_recorder,
            enable_profiler=False,
            runtime_buffer_size=16*1024*1024, # 16MB
        )

        disable_program_recorder = False
        if enable_accelerator_recorder:
            if tflm_model.accelerator is None:
                raise ValueError('Must provide accelerator when using enable_accelerator_recorder')
            tflm_model.accelerator.set_program_recorder_enabled(True)
            disable_program_recorder = True

        
        reenable_simulator_backend = False
        reenable_simulator_accelerator_cycles = False
        if disable_simulator_backend:
            if tflm_model.accelerator is None:
                raise ValueError('Must provide accelerator when using disable_simulator_backend')
            if hasattr(tflm_model.accelerator, 'set_simulator_backend_enabled'):
                reenable_simulator_backend = True
                tflm_model.accelerator.set_simulator_backend_enabled(False)
            if hasattr(tflm_model.accelerator, 'set_calculate_accelerator_cycles_only_enabled'):
                tflm_model.accelerator.set_calculate_accelerator_cycles_only_enabled(True)
            
        if layer_callback:
            tflm_model.set_layer_callback(functools.partial(
                _layer_callback_handler,
                tflite_model=tflite_model,
                callback=layer_callback
            ))

        try:
            if input_data is not None:
                if isinstance(input_data, list):
                    for i, v in enumerate(input_data):
                        tflm_model.input(index=i, value=v)
                else:
                    tflm_model.input(value=input_data)
            else:
                for i, inp in enumerate(tflite_model.inputs):
                    d = np.zeros_like(inp.data)
                    tflm_model.input(index=i, value=d)

            tflm_model.invoke()
            recorded_data = tflm_model.get_recorded_data()

            if reenable_simulator_backend:
                tflm_model.accelerator.set_simulator_backend_enabled(True)
            if reenable_simulator_accelerator_cycles:
                tflm_model.accelerator.set_calculate_accelerator_cycles_only_enabled(False)
            if disable_program_recorder:
                tflm_model.accelerator.set_program_recorder_enabled(False)


            retval = []

            for layer_index, recorded_layer_data in enumerate(recorded_data.get('layers', [])):
                # pylint: disable=protected-access
                tf_layer = tflite_model.layers[layer_index] if update_input_model \
                    else copy.deepcopy(tflite_model.layers[layer_index])
                retval.append(tf_layer)

                layer_err = tflm_model.get_layer_error(layer_index)
                tf_layer.metadata['error_msg'] = None if layer_err is None else layer_err.msg

                for input_index, input_bytes in enumerate(recorded_layer_data.get('inputs', [])):
                    if input_index >= tf_layer.n_inputs:
                        break
                    input_tensor = tf_layer.inputs[input_index]
                    if input_tensor is None:
                        continue
                    input_buf = np.frombuffer(input_bytes, dtype=input_tensor.dtype)
                    if input_tensor.shape.flat_size > 0:
                        tf_layer.inputs[input_index]._data = np.reshape(input_buf, newshape=input_tensor.shape)
                    else:
                        tf_layer.inputs[input_index]._data = input_buf

                for output_index, output_bytes in enumerate(recorded_layer_data.get('outputs', [])):
                    output_tensor = tf_layer.outputs[output_index]
                    output_buf = np.frombuffer(output_bytes, dtype=output_tensor.dtype)
                    if output_tensor.shape.flat_size > 0:
                        tf_layer.outputs[output_index]._data = np.reshape(output_buf, newshape=output_tensor.shape)
                    else:
                        tf_layer.outputs[output_index]._data = output_buf

                for key, value in recorded_layer_data.items():
                    if key not in ('inputs', 'outputs'):
                        tf_layer.metadata[key] = value

            if return_model_details:
                model_details = tflm_model.details
                _add_memory_plan(
                    tflite_model=tflite_model,
                    recorded_data=recorded_data,
                    model_details=model_details
                )
        finally:
            TfliteMicro.unload_model(tflm_model)

        if return_model_details:
            return retval, model_details

        return retval


    @staticmethod
    def add_accelerator_path(path:str):
        """Add an accelerator search path"""
        TfliteMicro._accelerator_paths.append(path)


    @staticmethod
    def register_accelerator(accelerator:TfliteMicroAccelerator):
        """Register a TFLM accelerator instance"""
        try:
            acc_api_version = accelerator.api_version
        except Exception as e:
            # pylint:disable=raise-missing-from
            raise RuntimeError(
                f'Failed to load accelerator: {accelerator.name}, ' + \
                f'failed to retrieve api version from wrapper, err: {e}')

        tflm_api_version = TfliteMicro.api_version()
        if tflm_api_version != acc_api_version:
            raise RuntimeError(
                f'Accelerator: {accelerator.name} not compatible, ' + \
                f'accelerator API version ({acc_api_version}) != TFLM wrapper version ({tflm_api_version})'
            )

        for variant in accelerator.variants:
            if TfliteMicro.accelerator_is_supported(variant):
                raise RuntimeError(f'Accelerator "{variant}" has already been registered')

            acc = copy.deepcopy(accelerator)
            acc.active_variant = variant
            TfliteMicro._accelerators[variant] = acc


    @staticmethod
    def get_accelerator(name:str) -> TfliteMicroAccelerator:
        """Return an instance to the specified accelerator wrapper"""

        TfliteMicro._load_wrapper()


        norm_accelerator = TfliteMicro.normalize_accelerator_name(name)
        if norm_accelerator is None:
            raise ValueError(f'Unknown accelerator: {name}. Known accelerators are: {", ".join(TfliteMicro.get_supported_accelerators())}')

        return TfliteMicro._accelerators[norm_accelerator]


    @staticmethod
    def _load_wrapper():
        """Load the TFLM C++ wrapper and return a refernce to the loaded module"""
        if TfliteMicro._wrapper is not None:
            return TfliteMicro._wrapper

        # Add this wrapper directory to the env PATH
        # This way, the wrapper DLL can find additional DLLs as necessary
        wrapper_dir = os.path.dirname(os.path.abspath(__file__))
        os.environ['PATH'] = wrapper_dir + os.pathsep + os.environ['PATH']
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(wrapper_dir)

        # Import the TFLM C++ python wrapper
        # For more details, see:
        # <mltk root>/cpp/tflite_micro_wrapper
        try:
            TfliteMicro._wrapper = importlib.import_module('mltk.core.tflite_micro._tflite_micro_wrapper')
        except (ImportError, ModuleNotFoundError) as e:
            append_exception_msg(e,
                f'Failed to import the tflite_micro_wrapper C++ shared library.\n' \
                'If you built the MLTK from source then this could mean you need to re-build the mltk package (e.g. "pip install -e .").\n' \
                'If you\'re running from a pre-built MLTK package (e.g. "pip install silabs-mltk"),\n' \
                f'ensure that the _tflite_micro_wrapper file exists at {wrapper_dir}.\n' \
                'If the file does not exist, try installing, e.g.: pip install silabs-mltk --force-reinstall\n\n'
            )
            raise

        # Initialize the wrapper
        TfliteMicro._wrapper.init()

        # Set the callback that will be invoked by the C++ library
        # log messages
        TfliteMicro._wrapper.set_logger_callback(TfliteMicro._wrapper_logger_callback)

        TfliteMicro._load_accelerators()

        return TfliteMicro._wrapper


    @staticmethod
    def _load_accelerators():
        """Load all the TFLM accelerators found in the search paths"""
        curdir = os.path.dirname(os.path.abspath(__file__))
        search_paths = []
        search_paths.extend(TfliteMicro._accelerator_paths)
        search_paths.extend(as_list(get_user_setting('accelerator_paths')))
        search_paths.append(f'{curdir}/accelerators/mvp')

        # Check if any "<accelerator name>_mltk_accelerator.pth" files are found in the Python Libs directory
        python_libs_dir = sysconfig.get_path('purelib')
        if os.path.exists(python_libs_dir):
            for fn in os.listdir(python_libs_dir):
                if not fn.endswith('_mltk_accelerator.pth'):
                    continue
                pth_path = f'{python_libs_dir}/{fn}'
                with open(pth_path, 'r') as f:
                    accelerator_package_base_dir = f.readline().strip()
                accelerator_name = fn[:-len('_mltk_accelerator.pth')]
                accelerator_dir = f'{accelerator_package_base_dir}/{accelerator_name}'

                # If the file does exist,
                # then add its path to the accelerator search path
                if os.path.exists(accelerator_dir):
                    search_paths.append(accelerator_dir)
                elif os.path.exists(f'{accelerator_dir}_wrapper'):
                    search_paths.append(f'{accelerator_dir}_wrapper')

        for search_path in search_paths:
            search_path = fullpath(search_path)
            init_py_path = f'{search_path}/__init__.py'
            if not os.path.exists(init_py_path):
                continue
            TfliteMicro._load_accelerator(search_path)

        TfliteMicro.register_accelerator(PlaceholderTfliteMicroAccelerator('cmsis'))



    @staticmethod
    def _load_accelerator(accelerator_dir:str) -> bool:
        """Attempt to load an accelerator Python module in the given directory"""
        logger = TfliteMicro.get_logger()
        try:
            accelerator_module = import_module_at_path(accelerator_dir)
        except Exception as e:
            logger.debug(f'Failed to import {accelerator_dir}, err: {e}', exc_info=e)
            return False

        tflm_accelerator = None
        for key in dir(accelerator_module):
            value = getattr(accelerator_module, key)
            if inspect.isclass(value) and issubclass(value, TfliteMicroAccelerator):
                # Create an accelerator instance
                try:
                    tflm_accelerator = value()
                    break
                except Exception as e:
                    logger.warning(f'Accelerator module: {accelerator_dir} failed to initialize, err: \n{e}')
                    return False
                
        if tflm_accelerator is None:
            logger.debug(f'Accelerator module: {accelerator_dir} does not contain a TfliteMicroAccelerator class definition')
            return False

        try:
            TfliteMicro.register_accelerator(tflm_accelerator)
        except Exception as e:
            logger.warning(f'Failed to register accelerator: {accelerator_dir}, err: {e}')
            return False

        return True


    @staticmethod
    def _clear_logged_errors():
        """Clear errors generated by C++ wrapper. This is used internally by the wrapper"""
        TfliteMicro._load_wrapper()
        TfliteMicro._logged_errors.clear()


    @staticmethod
    def _get_logged_errors() -> List[str]:
        """Return errors generated by C++ wrapper as a list. This is used internally by the wrapper"""
        TfliteMicro._load_wrapper()
        return TfliteMicro._logged_errors


    @staticmethod
    def _get_logged_errors_str() -> str:
        """Return errors generated by C++ wrapper as a string. This is used internally by the wrapper"""
        return "\n".join(TfliteMicro._get_logged_errors())


    @staticmethod
    def _wrapper_logger_callback(msg: str):
        """ This callback will be invoked by the TFLM C++ wrapper
        when it internally issues a log msg"""
        l = TfliteMicro.get_logger()
        if l is None:
            return

        errs = TfliteMicro._logged_errors

        level = msg[:2].strip()
        msg = msg[2:].strip()

        if level == 'D':
            l.debug(msg)
        elif level == 'I':
            l.info(msg)
        elif level == 'W':
            l.warning(msg)
            errs.append(msg)
        elif level == 'E':
            l.error(msg)
            errs.append(msg)


def _load_tflite_model(model:Union[str,TfliteModel]) -> TfliteModel:
    if isinstance(model, TfliteModel):
        return model

    elif isinstance(model, str):
        if not model.endswith('.tflite') or not os.path.exists(model):
            raise ValueError('Provided model must be a path to an existing .tflite file')
        return TfliteModel.load_flatbuffer_file(model)
    else:
        raise RuntimeError('Must provide TfliteModel or path to .tflite file')


def _add_memory_plan(
    tflite_model:TfliteModel,
    recorded_data:List,
    model_details:TfliteMicroModelDetails
):
    from .tflite_micro_memory_plan import TfliteMicroMemoryPlan

    recorded_data_layers = recorded_data.get('layers', [])
    model_details._memory_plan = TfliteMicroMemoryPlan.create( # pylint: disable=protected-access
        memory_plan=recorded_data.get('memory_plan', []),
        tflite_model=tflite_model,
        total_persistent_runtime_size=recorded_data.get('total_persistent_runtime_size', 0),
        temp_runtime_sizes=list(x.get('temp_memory_used', 0) for x in recorded_data_layers),
        persistent_runtime_sizes=list(x.get('persistent_memory_used', 0) for x in recorded_data_layers)
    )


def _layer_callback_handler(
    tflite_model:TfliteModel,
    callback:Callable[[TfliteLayer],bool], 
    index:int, 
    outputs:List[bytes]
) -> bool:
    tf_layer = copy.deepcopy(tflite_model.layers[index])
    for output_index, output_bytes in enumerate(outputs):
        output_tensor = tf_layer.outputs[output_index]
        output_buf = np.frombuffer(output_bytes, dtype=output_tensor.dtype)
        if output_tensor.shape.flat_size > 0:
            tf_layer.outputs[output_index]._data = np.reshape(output_buf, newshape=output_tensor.shape) # pylint: disable=protected-access
        else:
            tf_layer.outputs[output_index]._data = output_buf # pylint: disable=protected-access
        
    return callback(tf_layer)


def _retrieve_runtime_buffer_sizes(
    tflite_model:TfliteModel,
    accelerator:str,
    runtime_buffer_size:int,
) -> List[int]:
    from mltk.core.tflite_model_parameters import TfliteModelParameters
    runtime_buffer_sizes = [0]
    try:
        memory_spec = TfliteModelParameters.load_from_tflite_model(
            tflite_model, 
            tag=f'{accelerator}_memory_spec'
        )
    except:
        memory_spec = {}

    if memory_spec:
        runtime_buffer_sizes = memory_spec.get('sizes', [0])

    if runtime_buffer_size:
        runtime_buffer_sizes[0] = runtime_buffer_size

    return runtime_buffer_sizes