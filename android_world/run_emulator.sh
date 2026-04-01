EMULATOR_NAME=AndroidWorldAvd # From previous step
EMULATOR="/mnt/c/Users/quanp/AppData/Local/Android/Sdk/emulator/emulator.exe"

$EMULATOR -avd $EMULATOR_NAME -no-snapshot -grpc 8554