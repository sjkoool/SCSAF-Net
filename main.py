
import os
import cv2
import random
import numpy as np
import torch
import argparse
from shutil import copyfile
from src.config import Config
from src.SCSAF import SCSAF
import wandb


def main(mode=None):
    config_path = "XXX/config.yml"
    config = Config(config_path)
    config.print()

    # Initialize wandb
    with wandb.init(project='Rstormer', config=config):
        # Set CUDA visible devices
        os.environ['CUDA_VISIBLE_DEVICES'] = ','.join(str(e) for e in config.GPU)

        # Init device
        if torch.cuda.is_available():
            print('Cuda is available')
            config.DEVICE = torch.device("cuda")
            torch.backends.cudnn.benchmark = True  # cudnn auto-tuner
        else:
            print('Cuda is unavailable, use cpu')
            config.DEVICE = torch.device("cpu")

        # Set cv2 running threads to 1 (prevents deadlocks with pytorch dataloader)
        cv2.setNumThreads(0)

        # Initialize random seed
        torch.manual_seed(config.SEED)
        torch.cuda.manual_seed_all(config.SEED)
        np.random.seed(config.SEED)
        random.seed(config.SEED)

        # Build the model and initialize
        
        model = SCSAF(config)
        model.load()

        # Model training
        if config.MODE == 1:
            config.print()
            print('\nstart training...\n')
            model.train()

        # # Model test
        elif config.MODE == 2:
        # elif mode == 2:
            print('\nstart testing...\n')
            model.test()

def load_config(mode=None):
    """loads model config

    Args:
        mode (int): 1: train, 2: test, reads from config file if not specified
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--path', '--checkpoints', type=str, default='XXX',
                        help='model checkpoints path (default: ./checkpoints)')
    parser.add_argument('--model', type=int, default=2, choices=[2, 3])

    if mode == 2:
        parser.add_argument('--input', type=str, help='path to the input images directory or an input image')
        parser.add_argument('--mask', type=str, help='path to the masks directory or a mask file')
        parser.add_argument('--output', type=str, help='path to the output directory')

    args = parser.parse_args()
    config_path = os.path.join(args.path, 'config.yml')
    if not os.path.exists(config_path):
        copyfile('./config.yml', config_path)

    config = Config(config_path)
    print(f"Config path: {config_path}")

    if mode == 1:
        config.MODE = 1
        if args.model:
            config.MODEL = args.model

    elif mode == 2:
        config.MODE = 2
        config.MODEL = args.model if args.model is not None else 3

        if args.input:
            config.TEST_INPAINT_IMAGE_FLIST = args.input

        if args.mask:
            config.TEST_MASK_FLIST = args.mask

        if args.output:
            config.RESULTS = args.output

    return config

if __name__ == "__main__":
    main()


