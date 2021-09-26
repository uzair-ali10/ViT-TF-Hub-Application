# -*- coding: utf-8 -*-
"""Image_Scene_Classification_ViT_S32-Ligh-Augmentation.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/14Ms__eAJOD0jdDLlHxmIawcQET_GyQjz

## Setup
"""

!nvidia-smi

!pip install -q tensorflow-addons

"""## Data Gathering"""

!wget -q http://data.vision.ee.ethz.ch/ihnatova/camera_scene_detection_train.zip
!unzip -qq camera_scene_detection_train.zip

"""## Imports"""

import numpy as np
import matplotlib.pyplot as plt
from imutils import paths
from pprint import pprint
from collections import Counter
from sklearn.preprocessing import LabelEncoder

import tensorflow as tf
from tensorflow import keras
import tensorflow_hub as hub
import tensorflow_addons as tfa

SEEDS = 42

tf.random.set_seed(SEEDS)
np.random.seed(SEEDS)

"""## Data Parsing"""

image_paths = list(paths.list_images("training"))
np.random.shuffle(image_paths)
image_paths[:5]

"""## Counting number of images for each classes"""

labels = []
for image_path in image_paths:
    label = image_path.split("/")[1]
    labels.append(label)
class_count = Counter(labels) 
pprint(class_count)

"""## Splitting the dataset"""

TRAIN_SPLIT = 0.9

i = int(len(image_paths) * TRAIN_SPLIT)

train_paths = image_paths[:i]
train_labels = labels[:i]
validation_paths = image_paths[i:]
validation_labels = labels[i:]

print(len(train_paths), len(validation_paths))

"""## Define Hyperparameters"""

BATCH_SIZE = 128
AUTO = tf.data.AUTOTUNE
EPOCHS = 10
IMG_SIZE = 224
RESIZE_TO = 260
NUM_CLASSES = 30
TOTAL_STEPS = int((len(train_paths) / BATCH_SIZE) * EPOCHS)
WARMUP_STEPS = 10
INIT_LR = 0.03
WAMRUP_LR = 0.006

"""## Encoding labels"""

label_encoder = LabelEncoder()
train_labels_le = label_encoder.fit_transform(train_labels)
validation_labels_le = label_encoder.transform(validation_labels)
print(train_labels_le[:5])

"""## Determine the class-weights"""

trainLabels = keras.utils.to_categorical(train_labels_le)
classTotals = trainLabels.sum(axis=0)
classWeight = dict()
# loop over all classes and calculate the class weight
for i in range(0, len(classTotals)):
	classWeight[i] = classTotals.max() / classTotals[i]

"""## Convert the data into TensorFlow `Dataset` objects"""

train_ds = tf.data.Dataset.from_tensor_slices((train_paths, train_labels_le))
val_ds = tf.data.Dataset.from_tensor_slices((validation_paths, validation_labels_le))

"""## Define the preprocessing function"""

@tf.function  
def preprocess_train(image_path, label):
    image = tf.io.read_file(image_path)
    image = tf.image.decode_jpeg(image, channels=3)
    image = tf.image.resize(image, (RESIZE_TO, RESIZE_TO))
    image = tf.image.random_crop(image, [IMG_SIZE, IMG_SIZE, 3])
    image = tf.cast(image, tf.float32) / 255.0
    return (image, label)

@tf.function
def preprocess_test(image_path, label):
    image = tf.io.read_file(image_path)
    image = tf.image.decode_jpeg(image, channels=3)
    image = tf.image.resize(image, (IMG_SIZE, IMG_SIZE))
    image = tf.cast(image, tf.float32) / 255.0
    return (image, label)

"""## Data Augmentation"""

data_augmentation = tf.keras.Sequential(
    [
        tf.keras.layers.experimental.preprocessing.RandomFlip("horizontal_and_vertical"),
        tf.keras.layers.experimental.preprocessing.RandomRotation(factor=0.02),
        tf.keras.layers.experimental.preprocessing.RandomZoom(
            height_factor=0.2, width_factor=0.2
        ),
    ],
    name="data_augmentation",
)

"""## Create the Data Pipeline"""

pipeline_train = (
    train_ds
    .shuffle(BATCH_SIZE * 100)
    .map(preprocess_train, num_parallel_calls=AUTO)
    .batch(BATCH_SIZE)
    .map(lambda x, y: (data_augmentation(x), y), num_parallel_calls=AUTO)
    .prefetch(AUTO)
)

pipeline_validation = (
    val_ds
    .map(preprocess_test, num_parallel_calls=AUTO)
    .batch(BATCH_SIZE)
    .prefetch(AUTO)
)

"""## Visualise the training images"""

image_batch, label_batch = next(iter(pipeline_train))

plt.figure(figsize=(10, 10))
for i in range(9):
    ax = plt.subplot(3, 3, i + 1)
    plt.imshow(image_batch[i].numpy())
    label = label_batch[i]
    plt.title(label_encoder.inverse_transform([label.numpy()])[0])
    plt.axis("off")

"""## Load model into KerasLayer"""

def training_model(vit_model_url):
    model = keras.Sequential(
        [
            keras.layers.InputLayer((IMG_SIZE, IMG_SIZE, 3)),
            hub.KerasLayer(vit_model_url, trainable=True),
            keras.layers.Dense(NUM_CLASSES, activation="softmax"),
        ]
    )

    return model

model = training_model("https://tfhub.dev/sayakpaul/vit_r26_s32_lightaug_fe/1")

model.summary()

"""## Learning Rate Scheduling

For fine-tuning
"""

# Reference:
# https://www.kaggle.com/ashusma/training-rfcx-tensorflow-tpu-effnet-b2


class WarmUpCosine(keras.optimizers.schedules.LearningRateSchedule):
    def __init__(
        self, learning_rate_base, total_steps, warmup_learning_rate, warmup_steps
    ):
        super(WarmUpCosine, self).__init__()

        self.learning_rate_base = learning_rate_base
        self.total_steps = total_steps
        self.warmup_learning_rate = warmup_learning_rate
        self.warmup_steps = warmup_steps
        self.pi = tf.constant(np.pi)

    def __call__(self, step):
        if self.total_steps < self.warmup_steps:
            raise ValueError("Total_steps must be larger or equal to warmup_steps.")
        learning_rate = (
            0.5
            * self.learning_rate_base
            * (
                1
                + tf.cos(
                    self.pi
                    * (tf.cast(step, tf.float32) - self.warmup_steps)
                    / float(self.total_steps - self.warmup_steps)
                )
            )
        )

        if self.warmup_steps > 0:
            if self.learning_rate_base < self.warmup_learning_rate:
                raise ValueError(
                    "Learning_rate_base must be larger or equal to "
                    "warmup_learning_rate."
                )
            slope = (
                self.learning_rate_base - self.warmup_learning_rate
            ) / self.warmup_steps
            warmup_rate = slope * tf.cast(step, tf.float32) + self.warmup_learning_rate
            learning_rate = tf.where(
                step < self.warmup_steps, warmup_rate, learning_rate
            )
        return tf.where(
            step > self.total_steps, 0.0, learning_rate, name="learning_rate"
        )

scheduled_lrs = WarmUpCosine(
    learning_rate_base=INIT_LR,
    total_steps=TOTAL_STEPS,
    warmup_learning_rate=WAMRUP_LR,
    warmup_steps=WARMUP_STEPS,
)

lrs = [scheduled_lrs(step) for step in range(TOTAL_STEPS)]
plt.plot(lrs)
plt.xlabel("Step", fontsize=14)
plt.ylabel("LR", fontsize=14)
plt.show()

"""## Define optimizer and loss"""

optimizer = keras.optimizers.SGD(scheduled_lrs, clipnorm=1.0)
loss_fn = keras.losses.SparseCategoricalCrossentropy()

"""## Compile the model"""

model.compile(optimizer=optimizer, loss=loss_fn, metrics=['accuracy'])

"""## Setup Callbacks"""

train_callbacks = [
    keras.callbacks.EarlyStopping(monitor='val_accuracy', patience=3, restore_best_weights=True),
    keras.callbacks.CSVLogger('./train-logs.csv'),
    keras.callbacks.TensorBoard(histogram_freq=1)
]

"""## Train the model"""

history = model.fit(
    pipeline_train,
    batch_size=BATCH_SIZE,
    epochs= EPOCHS, 
    validation_data=pipeline_validation,
    class_weight=classWeight,
    callbacks=train_callbacks)

"""## Plot the Metrics"""

def plot_hist(hist):
    plt.plot(hist.history["accuracy"])
    plt.plot(hist.history["val_accuracy"])
    plt.plot(hist.history["loss"])
    plt.plot(hist.history["val_loss"])
    plt.title("Training Progress")
    plt.ylabel("Accuracy/Loss")
    plt.xlabel("Epochs")
    plt.legend(["train_acc", "val_acc", "train_loss", "val_loss"], loc="upper left")
    plt.show()

"""## Evaluate the model"""

accuracy = model.evaluate(pipeline_validation)[1] * 100
print("Accuracy: {:.2f}%".format(accuracy))
plot_hist(history)

"""## Upload the TensorBoard logs"""

!tensorboard dev upload --logdir logs --name "ViT-S32-Light-Augmentation Model" --description "ViT SS32-Light-Augmentation Model trained on Image-Scene-Dataset"

"""**Link:** https://tensorboard.dev/experiment/myd5IEZtRjWEmAQQ9lSolA/"""