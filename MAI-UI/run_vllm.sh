export HF_HUB_ENABLE_HF_TRANSFER=0
export HF_HUB_DOWNLOAD_THREADS=1


python -m vllm.entrypoints.openai.api_server \
    --model Tongyi-MAI/MAI-UI-2B \
    --served-model-name MAI-UI-2B \
    --host 0.0.0.0 \
    --port 8001 \
    --max_model_len 32768 \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code
