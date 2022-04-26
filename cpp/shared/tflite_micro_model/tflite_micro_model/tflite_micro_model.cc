#include <new>
#include <cstdlib>
#include "tensorflow/lite/schema/schema_generated.h"
#include "cpputils/string.hpp"
#include "tflite_micro_model/tflite_micro_model.hpp"
#include "tflite_micro_model/tflite_micro_utils.hpp"

#include "mltk_tflite_micro_internal.hpp"


namespace tflite
{
    // This was added by the MLTK in simple_memory_allocator.cc
    // It hold the maximum number of bytes allocated in the tensor arena
    // including temporary allocations
    extern uint32_t required_tensor_arena_bytes;
}

namespace mltk
{

void adjust_required_tensor_arena_bytes_from_64bit_to_32bit(
    const struct tflite::Model* tflite_model, 
    tflite::MicroInterpreter* interpreter
);


/*************************************************************************************************/
TfliteMicroModel::~TfliteMicroModel()
{
    unload();
}

/*************************************************************************************************/
bool TfliteMicroModel::load(
    const void* flatbuffer, 
    tflite::MicroOpResolver& op_resolver,
    uint8_t *runtime_buffer,
    unsigned runtime_buffer_size 
)
{
    auto accelerator = mltk_tflite_micro_get_registered_accelerator();

    // If no runtime buffer was specified,
    // then we need to allocate one now
    if(runtime_buffer == nullptr)
    {
        // If no buffer size was given, then retrieve it from the .tflite's model parameters metadata
        runtime_buffer_size = (runtime_buffer_size == 0) ? get_tensor_arena_size(flatbuffer) : runtime_buffer_size;
#ifndef __arm__
        // If this is a windows/linux build, the just allocate a large buffer
        // to ensure there is enough room
        runtime_buffer_size = 4*1024*1024;
#endif
        runtime_buffer = (uint8_t*)malloc(runtime_buffer_size);
        if(runtime_buffer == nullptr)
        {
            MLTK_ERROR("Failed to allocate tensor arena of size: %d", runtime_buffer_size);
            return false;
        }
        _runtime_buffer = runtime_buffer;
    }

    if(accelerator != nullptr)
    {
        accelerator->init();
    }

    auto tflite_model = tflite::GetModel(flatbuffer);
    _interpreter = new(_interpreter_buffer)tflite::MicroInterpreter(
        tflite_model,
        op_resolver,
        runtime_buffer, runtime_buffer_size,
        &_error_reporter
    );

    if(_interpreter->AllocateTensors() != kTfLiteOk)
    {
        MLTK_ERROR("Failed to allocate model tensors");
        unload();
        return false;
    }

    _ops_resolver = &op_resolver;
    _flatbuffer = flatbuffer;

    load_model_parameters();
    // Call this API which will also update the MLTK defined global variable: required_tensor_arena_bytes
    // with the maximum number of bytes allocated including temporary allocations
    _interpreter->arena_used_bytes();

#ifndef __arm__
    adjust_required_tensor_arena_bytes_from_64bit_to_32bit(tflite_model, _interpreter);
#endif
    _model_details._runtime_memory_size = tflite::required_tensor_arena_bytes;

    if(accelerator != nullptr)
    {
        _model_details._accelerator = accelerator->name;
#ifdef TFLITE_MICRO_SIMULATOR_ENABLED
        accelerator->set_simulator_memory("sram", runtime_buffer, _model_details._runtime_memory_size);
        accelerator->set_simulator_memory("flash", (void*)flatbuffer, 2*1024*1024);
#endif
    }


    return true;
}

/*************************************************************************************************/
void TfliteMicroModel::unload()
{
    auto accelerator = mltk_tflite_micro_get_registered_accelerator();

    if(accelerator != nullptr)
    {
        accelerator->deinit();
    }

    _flatbuffer = nullptr;
    _ops_resolver = nullptr;
    parameters.unload();
    _model_details.unload();
    TFLITE_MICRO_RECORDER_CLEAR();
    if(_interpreter != nullptr)
    {
        _interpreter->~MicroInterpreter();
        _interpreter = nullptr;
    }

    if(_runtime_buffer != nullptr)
    {
        free(_runtime_buffer);
        _runtime_buffer = nullptr;
    }
}

/*************************************************************************************************/
bool TfliteMicroModel::is_loaded() const
{
    return _interpreter != nullptr;
}

/*************************************************************************************************/
bool TfliteMicroModel::invoke() const
{
    bool retval;
    auto accelerator = mltk_tflite_micro_get_registered_accelerator();

    if(!is_loaded())
    {
        MLTK_ERROR("Model not loaded");
        return false;
    }

    if(recording_is_enabled())
    {
        TFLITE_MICRO_RECORDER_CLEAR();
    }
    if(profiler_is_enabled())
    {
        profiling::reset(this->profiler());
    }

    mltk::_processing_callback = this->_processing_callback;
    mltk::_processing_callback_arg = this->_processing_callback_arg;

#ifdef TFLITE_MICRO_SIMULATOR_ENABLED
    if(accelerator != nullptr)
    {
        retval = accelerator->invoke_simulator([this]() -> bool
        {
            return _interpreter->Invoke() == kTfLiteOk;
        });
    }
    else
    {
        retval = (_interpreter->Invoke() == kTfLiteOk);
    }
#else 
    retval = (_interpreter->Invoke() == kTfLiteOk);
#endif

    mltk::_processing_callback = nullptr;
    mltk::_processing_callback_arg = nullptr;

    return retval;
}

/*************************************************************************************************/
const TfliteMicroModelDetails& TfliteMicroModel::details() const
{
    return _model_details;
}

/*************************************************************************************************/
void TfliteMicroModel::print_summary(logging::Logger *logger) const
{
    auto& l = (logger != nullptr) ? *logger : get_logger();

    if(!is_loaded())
    {
        l.error("Model not loaded");
        return;
    }

    auto& input = *this->input(0);
    auto& output = *this->output(0);

    char fmt_buffer[32];
    const auto orig_flags = l.flags();
    l.flags(logging::Newline);

    l.info("Model details:");
    l.info("Name: %s", _model_details.name());
    l.info("Version: %d", _model_details.version());
    l.info("Date: %s", _model_details.date());
    l.info("Hash: %s", _model_details.hash());
    l.info("Accelerator: %s", _model_details.accelerator());
    
    l.info("Total runtime memory: %s", cpputils::format_units(_model_details.runtime_memory_size(), 3, fmt_buffer));;
    l.info("Input: %s", input.to_str());
    l.info("Output: %s", output.to_str());

    const auto& classes = _model_details.classes();
    const auto class_count = classes.size();
    if(class_count > 0)
    {
        l.flags().clear(logging::Newline);
        l.info("Classes: ");
        for(int i = 0; i < class_count; ++i)
        {
            l.info((i < class_count-1) ? "%s, " : "%s\n", classes[i]);
        }
        l.flags().set(logging::Newline);
    }
    
    if(*_model_details.description() != 0)
    {
        l.info("Description: %s", _model_details.description());
    }
    
    l.flags(orig_flags);
}

/*************************************************************************************************/
unsigned TfliteMicroModel::input_size() const
{
    if(!is_loaded())
    {
        MLTK_ERROR("Model not loaded");
        return false;
    }

    return _interpreter->inputs_size();
}

/*************************************************************************************************/
TfliteTensorView* TfliteMicroModel::input(unsigned index) const
{
    if(!is_loaded())
    {
        MLTK_ERROR("Model not loaded");
        return nullptr;
    }

    return reinterpret_cast<TfliteTensorView*>(_interpreter->input(index));
}

/*************************************************************************************************/
unsigned TfliteMicroModel::output_size() const
{
    if(!is_loaded())
    {
        MLTK_ERROR("Model not loaded");
        return false;
    }

    return _interpreter->outputs_size();
}

/*************************************************************************************************/
TfliteTensorView* TfliteMicroModel::output(unsigned index) const
{
    if(!is_loaded())
    {
        MLTK_ERROR("Model not loaded");
        return nullptr;
    }

    return reinterpret_cast<TfliteTensorView*>(_interpreter->output(index));
}

/*************************************************************************************************/
bool TfliteMicroModel::enable_profiler()
{
#ifdef TFLITE_MICRO_PROFILER_ENABLED
    if(is_loaded())
    {
        MLTK_ERROR("Model already loaded");
        return false;
    }
    model_profiler_enabled = true;
    return true;
#else
    MLTK_ERROR("C++ library not build with profiling support");
    return false;
#endif
}

/*************************************************************************************************/
bool TfliteMicroModel::profiler_is_enabled() const
{
    return model_profiler_enabled;
}

/*************************************************************************************************/
profiling::Profiler* TfliteMicroModel::profiler() const
{
    return profiling::get("Inference");
}

/*************************************************************************************************/
bool TfliteMicroModel::enable_recorder()
{
#if TFLITE_MICRO_RECORDER_ENABLED
    if(is_loaded())
    {
        MLTK_ERROR("Model already loaded");
        return false;
    }
    model_recorder_enabled = true;
    return true;
#else
    MLTK_ERROR("C++ library not build with recording support");
    return false;
#endif
}

/*************************************************************************************************/
bool TfliteMicroModel::recording_is_enabled() const
{
    return model_recorder_enabled;
}

/*************************************************************************************************/
#ifdef TFLITE_MICRO_RECORDER_ENABLED
TfliteMicroRecordedData& TfliteMicroModel::recorded_data()
{
    return TfliteMicroRecordedData::instance();
}
#endif

/*************************************************************************************************/
void TfliteMicroModel::set_processing_callback(void (*callback)(void*), void *arg)
{
    _processing_callback = callback;
    _processing_callback_arg = arg;
}

/*************************************************************************************************/
const void* TfliteMicroModel::find_metadata(const char* tag, uint32_t* length) const
{
    return get_metadata_from_tflite_flatbuffer(this->_flatbuffer, tag, length);
}

/*************************************************************************************************/
bool TfliteMicroModel::load_model_parameters()
{
    if(TfliteModelParameters::load_from_tflite_flatbuffer(this->_flatbuffer, this->parameters))
    {
         _model_details.load_parameters(&this->parameters);
         return true;
    }
    else 
    {
        return false;
    }
}


/*************************************************************************************************
 * The following code is used to account for the overhead 64-bit builds add to the runtime memory size.
 * Recall that embedded builds use 32-bit.
 * The following reduces the runtime memory size to convert from 64-bit pointers to 32-bit pointers.
 * The values below were experimentally found
 */
void adjust_required_tensor_arena_bytes_from_64bit_to_32bit(
    const struct tflite::Model* tflite_model, 
    tflite::MicroInterpreter* interpreter
)
{
    const auto& subgraph = *tflite_model->subgraphs()->Get(0);
    const int tensor_count = subgraph.tensors()->size();
    const int input_count = subgraph.inputs()->size();
    const int output_count = subgraph.outputs()->size();
    const int layer_count = subgraph.operators()->size();
    const int scratch_buffer_count = interpreter->allocator_.scratch_buffer_request_count_;
    int quantize_count = 0;
    int additional_pointer_count = 0;

    for(int i = 0; i < input_count; ++i)
    {
        int index = subgraph.inputs()->Get(i);
        auto tensor = subgraph.tensors()->Get(index);
        if(tensor->quantization() != nullptr)
        {
            ++quantize_count;
        }
    }
    for(int i = 0; i < output_count; ++i)
    {
        int index = subgraph.outputs()->Get(i);
        auto tensor = subgraph.tensors()->Get(index);
        if(tensor->quantization() != nullptr)
        {
            ++quantize_count;
        }
    }

    // Account for the pointers defined in the various MVP kernel OpData structs
    auto accelerator = mltk_tflite_micro_get_registered_accelerator();
    if(accelerator != nullptr && strcmp(accelerator->name, "MVP") == 0)
    {
        const auto& operators = *subgraph.operators();
        const auto& opcodes = *tflite_model->operator_codes();
        for(const auto op : operators)
        {
            const auto& opcode = opcodes[op->opcode_index()];

            if(opcode->builtin_code() == tflite::BuiltinOperator_ADD)
            {
                additional_pointer_count += 3;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_CONV_2D)
            {
                additional_pointer_count += 7;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_DEPTHWISE_CONV_2D)
            {
                additional_pointer_count += 7;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_FULLY_CONNECTED)
            {
                additional_pointer_count += 5;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_AVERAGE_POOL_2D)
            {
                additional_pointer_count += 2;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_MAX_POOL_2D)
            {
                additional_pointer_count += 2;
            }
            else if(opcode->builtin_code() == tflite::BuiltinOperator_TRANSPOSE_CONV)
            {
                additional_pointer_count += 8;
            }
        }   
    }

    const uint32_t overhead_64bit = \
        56*2 + /* SimpleMemoryAllocator x 2 */ \
        72 + /* GreedyMemoryPlanner */ \
        64 + /* MicroAllocator */ \
        16 + /* MicroBuiltinDataAllocator */ \
        16 + /* SubgraphAllocations */ \
        24*tensor_count + /* TfLiteEvalTensor*/ \
        64*layer_count  + /* NodeAndRegistration*/ \
        8*scratch_buffer_count + /* ScratchBufferHandle*/ \
        (8+64)*input_count + /* input TfLiteTensor* + TfLiteTensor */ \
        (8+64)*output_count + /* output TfLiteTensor* + TfLiteTensor */ \
        24 * quantize_count + /*  TfLiteAffineQuantization */ \
        8 * additional_pointer_count;

    const uint32_t overhead_32bit = \
        28*2 + /* SimpleMemoryAllocator x 2 */ \
        44 + /* GreedyMemoryPlanner */ \
        32 + /* MicroAllocator */ \
        8 + /* MicroBuiltinDataAllocator */ \
        8 + /* SubgraphAllocations */ \
        12*tensor_count + /* TfLiteEvalTensor*/ \
        32*layer_count  + /* NodeAndRegistration*/ \
        4*scratch_buffer_count + /* ScratchBufferHandle*/ \
        (4+32)*input_count + /* input TfLiteTensor* + TfLiteTensor */ \
        (4+32)*output_count + /* output TfLiteTensor* + TfLiteTensor */ \
        12 * quantize_count + /*  TfLiteAffineQuantization */ \
        4 * additional_pointer_count;

    tflite::required_tensor_arena_bytes -= overhead_64bit;
    tflite::required_tensor_arena_bytes += overhead_32bit;
}

} // namespace mltk