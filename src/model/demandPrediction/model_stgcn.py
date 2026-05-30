import geopandas as gpd
from pathlib import Path
import scipy.linalg as sl
from scipy.spatial.distance import cdist
from shapely import wkt
import pandas as pd
import numpy as np
import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

def build_stgcn(
    num_nodes: int,
    in_channels: int,
    time_steps: int,
    residual: bool,
    drop_out: float,
    hidden_channels: int=64,
    kernel_size: int=3,
    num_blocks: int=2,
):
    import keras
    from layers.stgcn import STGCNBlock
    from layers.adaptive_adjacency import AdaptiveAdjacency
    # Inputs
    x_in = keras.layers.Input(
        shape=(time_steps, num_nodes, in_channels),
        name="features",
    )

    A_tensor = AdaptiveAdjacency(num_nodes= num_nodes, embed_dim= 64, name = "adaptive_adj")(x_in)
    # 1. Initial Projection 
    # Project raw features (e.g., 1 channel) up to the hidden dimension (e.g., 64)
    # This gives the network capacity before the first STGCN block.
    x = keras.layers.Conv2D(
        filters=hidden_channels, 
        kernel_size=(1, 1), 
        name="input_projection"
    )(x_in)

    # 2. Stack Pre-Norm Blocks 
    for b in range(num_blocks):
        x = STGCNBlock(
            channels=hidden_channels,
            kernel_size=kernel_size,
            dropout_rate=drop_out,
            use_residual=residual,
            name=f"stgcn_block_{b+1}",
        )([x, A_tensor])  # Output: (batch, T, N, hidden_channels)

    # 3. Take representation at final time step
    # x_final: (batch, N, hidden_channels)
    x_final = x[:, -1, :, :]

    # 4. Per-node prediction
    out = keras.layers.Dense(1, activation="relu", name="output")(x_final)

    model = keras.Model(inputs=x_in, outputs=out, name="STGCN")

    return model

def train_model(model_path: str, use_fhvhv: bool):
    import os

    os.environ["KERAS_BACKEND"] = "torch"  # Or "jax" / "torch"

    import keras
    from layers.stgcn import STGCNBlock
    from dataclasses import dataclass
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from keras.callbacks import ModelCheckpoint, EarlyStopping, ReduceLROnPlateau
    from keras.optimizers import Adam
    from keras.losses import MeanSquaredError
    from dataset.taxi_demand import TaxiDemand, FHVHVTaxiDemand
    from keras.models import load_model
    import gc
    @dataclass
    class dates:
        start_year: int
        start_month: int
        end_year: int
        end_month: int
    input_steps = 12
    target_index = 0
    batch_size = 32
    epochs = 100
    train_dates = dates(2025,1,2025,7)
    val_dates = dates(2025,7, 2025,10)
    test_dates = dates(2025,10,2026,1)
    use_val = True
    if use_val:
        monitor = "val_loss"
    else:
        monitor = "loss"
    if use_fhvhv:
        train = FHVHVTaxiDemand(train_dates.start_year, train_dates.start_month, train_dates.end_year, train_dates.end_month)
        val = FHVHVTaxiDemand(val_dates.start_year, val_dates.start_month, val_dates.end_year, val_dates.end_month)
        test = FHVHVTaxiDemand(test_dates.start_year, test_dates.start_month, test_dates.end_year, test_dates.end_month)
    else:
        train = TaxiDemand(train_dates.start_year, train_dates.start_month, train_dates.end_year, train_dates.end_month)
        val = TaxiDemand(val_dates.start_year, val_dates.start_month, val_dates.end_year, val_dates.end_month)
        test = TaxiDemand(test_dates.start_year, test_dates.start_month, test_dates.end_year, test_dates.end_month)

    feature_list = ['pickups', 'precipitation', 'wind_speed_10m', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos']

    data_train = train.prepare_dataset(feature_list)
    X_train, Y_train = train.construct_dataset(data_train, input_steps, target_index)
    data_val= val.prepare_dataset(feature_list)
    X_val, Y_val = val.construct_dataset(data_val, input_steps, target_index)
    data_test = test.prepare_dataset(feature_list)
    X_test, Y_test = train.construct_dataset(data_test, input_steps, target_index)

    in_channels = data_train.shape[2]
    num_nodes = 263
    stgcn_model = build_stgcn(
        num_nodes=num_nodes,
        in_channels=in_channels,
        time_steps=input_steps,
        residual= True,
        drop_out = 0.3,
        hidden_channels=256,
        kernel_size=3,
        num_blocks=2,
    )
    stgcn_model.compile(
        optimizer=Adam(learning_rate=1e-3),
        loss=MeanSquaredError()
    )

    class ClearMemoryCallback(keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            gc.collect()
    clear_memory = ClearMemoryCallback()
    checkpoint = ModelCheckpoint(
                filepath=model_path, 
                monitor=monitor, 
                save_best_only=True, 
                verbose=0
                )
    
    # Stop training if validation loss hasn't improved for 10 epochs
    early_stopping = EarlyStopping(
        monitor=monitor, 
        patience=10, 
        restore_best_weights=True, 
        verbose=0
    )

    # Reduce learning rate by half if validation loss plateaus for 5 epochs
    lr_scheduler = ReduceLROnPlateau(
        monitor=monitor, 
        factor=0.5, 
        patience=8, 
        min_lr=1e-6, 
        verbose=0
    )

    callbacks = [clear_memory, checkpoint, lr_scheduler]
    print(stgcn_model.summary())

    if use_val:
        history = stgcn_model.fit(
            X_train, Y_train,
            batch_size=batch_size,
            epochs=epochs,
            validation_data=(X_val, Y_val),
            callbacks = callbacks
        )
    else:
        history = stgcn_model.fit(
            X_train, Y_train,
            batch_size=batch_size,
            epochs=epochs,
            callbacks = callbacks
        )
    best_model = load_model(
        model_path, 
        compile=False
    )
    y_pred = best_model.predict(X_test, batch_size=batch_size)
    print(f"MSE: {mean_squared_error(y_pred.flatten(), Y_test.flatten())}")
    print(f"MAE: {mean_absolute_error(y_pred.flatten(), Y_test.flatten())}")
    print(f"R2: {r2_score(y_pred.flatten(), Y_test.flatten())}")
    return history, best_model

def main(model_path:str, training: bool = True, use_fhvhv: bool = False):
    if training:
        train_model(model_path, use_fhvhv)


if __name__ == "__main__":
    import sys 
    if len(sys.argv) > 4:
        print("Usage: <save_path> [y|n] [y|n]")
        print("\t This trains a stgcn model and saves it in <save_path>")
        print("An example usage is 'uv run <path from root project>/model_stgcn.py best_stgcn'")
        exit()
    save_path = f"{sys.argv[1]}.keras"
    training = sys.argv[2] != "n"
    use_fhvhv = sys.argv[3] != "n"
    main(save_path, training, use_fhvhv)