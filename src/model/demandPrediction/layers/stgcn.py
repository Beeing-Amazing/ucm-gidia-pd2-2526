import keras
from keras import layers
from keras import activations
from ..layers.gcn import GraphConvolution
from ..layers.temp_conv import TempConvolution

@keras.saving.register_keras_serializable(package= "Museekar")
class STGCNBlock(layers.Layer):
    """
    A standard STGCN block that uses pre-norm. Does the following operations

    input -> x , residual

    x -> layerNormalization -> temp_conv1 -> GLU -> layerNormalization ->  gcn -> layerNormalization -> temp_conv2 -> GLU -> activation -> dropout 

    x + residual -> output
    """
    def __init__(
        self,
        channels: int,
        activation=None,
        kernel_size: int = 3,
        use_residual: bool = True,
        dropout_rate: float = 0.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.channels = channels
        self.kernel_size = kernel_size
        self.use_residual = use_residual
        self.dropout_rate = dropout_rate
        self.layer_norm_1 = layers.LayerNormalization(axis=-1)
        self.layer_norm_2 = layers.LayerNormalization(axis=-1)
        self.layer_norm_3 = layers.LayerNormalization(axis=-1)
        # Temporal convs: 2D conv with kernel (time, 1) so it only moves along T
        self.temp_conv1 = TempConvolution(
            units=channels,
            kernel_size=kernel_size,
            padding="same",
            activation=None,
            use_bias=True
        )

        self.activation = activations.get(activation)
        self.gcn = GraphConvolution(units=channels, activation=None, use_bias=False)
        
        self.temp_conv2 = TempConvolution(
            units=channels,
            kernel_size=kernel_size,
            padding="same",
            activation=None,
            use_bias=True
        )
        self.dropout = layers.Dropout(dropout_rate) if dropout_rate > 0.0 else None
        if self.use_residual:
            self.residual_conv = layers.Conv2D(
                filters=self.channels,
                kernel_size=(1, 1),
                padding="same",
                activation=None,
                name="residual_conv",
            )
    def build(self, input_shape):
        # input: [(B, T, N, F_in) (N, N)]
        x_shape, A_shape = input_shape
        b, t, n, f_in = x_shape        

        super().build(input_shape)

    def call(self, inputs, training=None):
        """
        Args:
            inputs: Tensor of shape (B, T, N, F_in) and Adjacency Matrix (N, N).
        Returns:
            Tensor of shape (B, T, N, channels).
        """
        x, A = inputs  # (B, T, N, F_in)
        
        # Prepare residual connection
        residual = x
        if self.use_residual and x.shape[3] != self.channels:
            residual = self.residual_conv(residual)  # (B, T, N, C)

        # First Temporal Conv

        x = self.layer_norm_1(x)
        x = self.temp_conv1(x)  # (B, T, N, C)

        # Spatial Graph Conv (per time step, per node)
        x = self.layer_norm_2(x)
        x = self.gcn([x, A])  # (B, T, N, C)
        if self.activation is not None:
            x = self.activation(x)

        # Second Temporal Conv
        x = self.layer_norm_3(x)
        x = self.temp_conv2(x)  # (B, T, N, C)

        if self.dropout is not None:
            x = self.dropout(x, training=training)

        # Add Residual Connection
        if self.use_residual:
            x = x + residual

        return x
    
    def get_config(self):
        config = super().get_config()
        config.update({
            "channels": self.channels,
            "kernel_size": self.kernel_size,
            "use_residual": self.use_residual,
            "dropout_rate": self.dropout_rate,
            "activation": activations.serialize(self.activation)
        })
        return config
