cd "$(dirname "$0")/evaluation/grounding"

# the env should be grounding

python eval_server.py \
    --dataset_dir /home/pquan/workspace/gui_datasets/ScreenSpot-Pro/annotations \
    --image_root /home/pquan/workspace/gui_datasets/ScreenSpot-Pro/images \
    --output_file ./output_server/SSPro_MAI-UI-8B.jsonl \
    --server_ip localhost \
    --server_port 8001 \
    --model_name MAI-UI-2B \
    --api_key EMPTY \
    --num_workers 4 --zoom_in
