@echo off
set device=0

:: 第一部分：MVTec测试
set depth=9
set n_ctx=12
set t_n_ctx=4
set base_dir=%depth%_%n_ctx%_%t_n_ctx%_multiscale
set save_dir=./checkpoints/%base_dir%/
set LOG=%save_dir%res.log
echo %LOG%
set CUDA_VISIBLE_DEVICES=%device%
python test.py ^
    --dataset mvtec ^
    --data_path /remote-home/iot_zhouqihang/data/mvdataset ^
    --save_path ./results/%base_dir%/zero_shot ^
    --checkpoint_path %save_dir%epoch_15.pth ^
    --features_list 24 ^
    --image_size 518 ^
    --depth %depth% ^
    --n_ctx %n_ctx% ^
    --t_n_ctx %t_n_ctx%

:: 第二部分：VisA测试
set base_dir=%depth%_%n_ctx%_%t_n_ctx%_multiscale_visa
set save_dir=./checkpoints/%base_dir%/
set LOG=%save_dir%res.log
echo %LOG%
python test.py ^
    --dataset VisA ^
    --data_path /remote-home/iot_zhouqihang/data/Visa ^
    --json_path /remote-home/iot_zhouqihang/data/Visa/meta.json ^
    --save_path ./results/%base_dir%/zero_shot ^
    --checkpoint_path %save_dir%epoch_15.pth ^
    --features_list 24 ^
    --image_size 224 ^
    --depth %depth% ^
    --n_ctx %n_ctx% ^
    --t_n_ctx %t_n_ctx%

pause