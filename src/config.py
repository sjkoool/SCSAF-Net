import os
import yaml

DEFAULT_CONFIG = {
    'MODE': 1,                      # 1: train, 2: test, 3: eval
    'MODEL': 1,                     # 1: edge model, 2: inpaint model, 3: edge-inpaint model, 4: joint model
    'MASK': 3,                      # 1: random block, 2: half, 3: external, 4: (external, random block), 5: (external, random block, half)
    'NMS': 1,                       # 0: no non-max-suppression, 1: applies non-max-suppression on the external edges by multiplying by Canny
    'SEED': 10,                     # random seed
    'GPU': [0],                     # list of gpu ids
    'AUGMENTATION_TRAIN': 0,        # 1: train 0: false use augmentation to train landmark predictor

    'LR': 0.0001,                   # learning rate
    'D2G_LR': 0.1,                  # discriminator/generator learning rate ratio
    'BETA1': 0.0,                   # adam optimizer beta1
    'BETA2': 0.9,                   # adam optimizer beta2
    'BATCH_SIZE': 2,                # input batch size for training
    'INPUT_SIZE': 256,              # input image size for training 0 for original size
    'MAX_ITERS': 2e6,               # maximum number of iterations to train the model

    'L1_LOSS_WEIGHT': 1,            # l1 loss weighthin
    'STYLE_LOSS_WEIGHT': 1,         # style loss weight
    'CONTENT_LOSS_WEIGHT': 1,       # perceptual loss weight
    'INPAINT_ADV_LOSS_WEIGHT': 0.01,# adversarial loss weight
    'TV_LOSS_WEIGHT': 0.1,          # total variation loss weight

    'GAN_LOSS': 'lsgan',            # nsgan | lsgan | hinge
    'GAN_POOL_SIZE': 0,             # fake images pool size

    'SAVE_INTERVAL': 1000,          # how many iterations to wait before saving model (0: never)
    'SAMPLE_INTERVAL': 1000,        # how many iterations to wait before sampling (0: never)
    'SAMPLE_SIZE': 12,              # number of images to sample
    'EVAL_INTERVAL': 0,             # how many iterations to wait before model evaluation (0: never)
    'LOG_INTERVAL': 10,             # how many iterations to wait before logging training status (0: never)
    'VERBOSE': True                 # 添加 VERBOSE 属性
}


class Config:
    def __init__(self, config_path):
        self._dict = DEFAULT_CONFIG.copy()  # Start with default config
        self._dict.update(self.load_config(config_path))  # Update with file contents
    def __getattr__(self, name):
        print(f"Accessing attribute: {name}")
        _dict = self.__dict__.get('_dict', {})
        if name in _dict:
            return _dict[name]
        raise AttributeError(f"'Config' object has no attribute '{name}'")

    def load_config(self, path):
        with open(path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)

    def print(self):
        print('Model configurations:')
        print('---------------------------------')
        for key, value in self._dict.items():
            print(f"{key}: {value}")
        print('---------------------------------')


if __name__ == "__main__":
    config_path = "XXX.config.yml"


    config = Config(config_path)
    config.print()
