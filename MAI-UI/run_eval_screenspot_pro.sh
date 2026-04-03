cd "$(dirname "$0")/evaluation/grounding"

# the env should be grounding

datadir=/data/Android/data
model="MAI-UI-8B"

python eval_server.py \
    --dataset_dir ${datadir}/ScreenSpot-Pro/annotations \
    --image_root ${datadir}/ScreenSpot-Pro/images \
    --output_file ./output_server/SSPro_MAI-UI-8B.jsonl \
    --server_ip localhost \
    --server_port 8001 \
    --model_name MAI-UI-8B \
    --api_key EMPTY \
    --num_workers 16 --zoom_in
