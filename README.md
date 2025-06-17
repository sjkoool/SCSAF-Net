# SCSAF-Net
This is a deep learning model for image inpainting and restoration.


Requirements:PyTorch  2.1.0，Python  3.10，CUDA  12.1


Install Dependencies  
This project requires the following Python packages. Before you start, install all dependencies:   
pip install einops    
pip install wandb  
pip install lpips
pip install scikit-image
pip install imageio
pip install scipy  
pip install opencv-python  
pip install pillow  
pip install matplotlib  
Configuration  
First, configure the paths and parameters in the `config.yml` file (including but not limited to the `.pth` file save path, test image path, training image path, and the number of iterations, etc.).
You need to edit this file according to your environment and requirements.


Configure the location of the `config.yml` file in `src/config.py`, and set the `config.yml` path in `src/main.py`.
Choose the mode in `config.yml`: set **1** for training and **2** for testing.
Run `python train.py` or `python test.py`.
