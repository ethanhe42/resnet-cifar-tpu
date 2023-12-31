
# %% 
# export XRT_TPU_CONFIG="localservice;0;localhost:51011"
# ! pip install --quiet "torchmetrics>=0.7, <0.12" "setuptools==67.4.0" "ipython[notebook]>=8.0.0, <8.12.0" "torch>=1.8.1, <1.14.0" "torchvision" "pytorch-lightning>=1.4, <2.0.0"

# %%
import os

import lightning as L
from lightning.pytorch.loggers import WandbLogger
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader, random_split
from torchmetrics.functional import accuracy
from torchvision import transforms


# Note - you must have torchvision installed for this example
from torchvision.datasets import CIFAR10, MNIST

PATH_DATASETS = os.environ.get("PATH_DATASETS", ".")
BATCH_SIZE = 256 if torch.cuda.is_available() else 64

# %% [markdown]
# ## Using DataModules
# 
# DataModules are a way of decoupling data-related hooks from the `LightningModule
# ` so you can develop dataset agnostic models.

# %% [markdown]
# ### Defining The MNISTDataModule
# 
# Let's go over each function in the class below and talk about what they're doing:
# 
# 1. ```__init__```
#     - Takes in a `data_dir` arg that points to where you have downloaded/wish to download the MNIST dataset.
#     - Defines a transform that will be applied across train, val, and test dataset splits.
#     - Defines default `self.dims`.
# 
# 
# 2. ```prepare_data```
#     - This is where we can download the dataset. We point to our desired dataset and ask torchvision's `MNIST` dataset class to download if the dataset isn't found there.
#     - **Note we do not make any state assignments in this function** (i.e. `self.something = ...`)
# 
# 3. ```setup```
#     - Loads in data from file and prepares PyTorch tensor datasets for each split (train, val, test).
#     - Setup expects a 'stage' arg which is used to separate logic for 'fit' and 'test'.
#     - If you don't mind loading all your datasets at once, you can set up a condition to allow for both 'fit' related setup and 'test' related setup to run whenever `None` is passed to `stage`.
#     - **Note this runs across all GPUs and it *is* safe to make state assignments here**
# 
# 
# 4. ```x_dataloader```
#     - `train_dataloader()`, `val_dataloader()`, and `test_dataloader()` all return PyTorch `DataLoader` instances that are created by wrapping their respective datasets that we prepared in `setup()`

# %%
# class MNISTDataModule(L.LightningDataModule):
#     def __init__(self, data_dir: str = PATH_DATASETS):
#         super().__init__()
#         self.data_dir = data_dir
#         self.transform = transforms.Compose(
#             [
#                 transforms.ToTensor(),
#                 transforms.Normalize((0.1307,), (0.3081,)),
#             ]
#         )

#         self.dims = (1, 28, 28)
#         self.num_classes = 10

#     def prepare_data(self):
#         # download
#         MNIST(self.data_dir, train=True, download=True)
#         MNIST(self.data_dir, train=False, download=True)

#     def setup(self, stage=None):
#         # Assign train/val datasets for use in dataloaders
#         if stage == "fit" or stage is None:
#             mnist_full = MNIST(self.data_dir, train=True, transform=self.transform)
#             self.mnist_train, self.mnist_val = random_split(mnist_full, [55000, 5000])

#         # Assign test dataset for use in dataloader(s)
#         if stage == "test" or stage is None:
#             self.mnist_test = MNIST(self.data_dir, train=False, transform=self.transform)

#     def train_dataloader(self):
#         return DataLoader(self.mnist_train, batch_size=BATCH_SIZE)

#     def val_dataloader(self):
#         return DataLoader(self.mnist_val, batch_size=BATCH_SIZE)

#     def test_dataloader(self):
#         return DataLoader(self.mnist_test, batch_size=BATCH_SIZE)

# %% [markdown]
# ### Defining the dataset agnostic `LitModel`
# 
# Below, we define the same model as the `LitMNIST` model we made earlier.
# 
# However, this time our model has the freedom to use any input data that we'd like 

# %%
class LitModel(L.LightningModule):
    def __init__(self):
        super().__init__()

        from resnet_cifar import resnet20, resnet56, resnet1202
        self.model = resnet20() #resnet1202()

    def forward(self, x):
        x = self.model(x)
        return F.log_softmax(x, dim=1)

    def training_step(self, batch):
        x, y = batch
        logits = self(x)
        loss = F.nll_loss(logits, y)
        self.log("train_loss", loss, prog_bar=True, sync_dist=True)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.nll_loss(logits, y)
        
        acc = torch.sum(torch.argmax(logits, dim=1) == y) / len(y)
        self.log("val_loss", loss, prog_bar=True, sync_dist=True)
        self.log("val_acc", acc, prog_bar=True, sync_dist=True)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters())
        return optimizer

# %% [markdown]
# ### Training the `LitModel` using the `MNISTDataModule`
# 
# Now, we initialize and train the `LitModel` using the `MNISTDataModule`'s configuration settings and dataloaders.

# %%
# # Init DataModule
# dm = MNISTDataModule()
# # Init model from datamodule's attributes
# model = LitModel(*dm.dims, dm.num_classes)
# # Init trainer
# trainer = L.Trainer(
#     max_epochs=3,
#     accelerator="auto",
#     devices=1,
# )
# # Pass the datamodule as arg to trainer.fit to override model hooks :)
# trainer.fit(model, dm)

# %% [markdown]
# ### Defining the CIFAR10 DataModule
# 
# Lets prove the `LitModel` we made earlier is dataset agnostic by defining a new datamodule for the CIFAR10 dataset.

# %%
class CIFAR10DataModule(L.LightningDataModule):
    def __init__(self, data_dir: str = "./"):
        super().__init__()
        self.data_dir = data_dir
        self.transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        )

        self.dims = (3, 32, 32)
        self.num_classes = 10

    def prepare_data(self):
        # download
        CIFAR10(self.data_dir, train=True, download=True)
        CIFAR10(self.data_dir, train=False, download=True)

    def setup(self, stage=None):
        # Assign train/val datasets for use in dataloaders
        if stage == "fit" or stage is None:
            cifar_full = CIFAR10(self.data_dir, train=True, transform=self.transform)
            self.cifar_train, self.cifar_val = random_split(cifar_full, [45000, 5000])

        # Assign test dataset for use in dataloader(s)
        if stage == "test" or stage is None:
            self.cifar_test = CIFAR10(self.data_dir, train=False, transform=self.transform)

    def train_dataloader(self):
        return DataLoader(self.cifar_train, batch_size=BATCH_SIZE)

    def val_dataloader(self):
        return DataLoader(self.cifar_val, batch_size=BATCH_SIZE)

    def test_dataloader(self):
        return DataLoader(self.cifar_test, batch_size=BATCH_SIZE)

# %% [markdown]
# ### Training the `LitModel` using the `CIFAR10DataModule`
# 
# Our model isn't very good, so it will perform pretty badly on the CIFAR10 dataset.
# 
# The point here is that we can see that our `LitModel` has no problem using a different datamodule as its input data.

# %%
dm = CIFAR10DataModule()
model = LitModel()
trainer = L.Trainer(
    accelerator="auto", devices="auto", strategy="auto",
    logger=WandbLogger(),
    max_epochs=10,
)
trainer.fit(model, dm)


