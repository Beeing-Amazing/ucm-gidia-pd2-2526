import keras
from keras import ops
from keras.layers import Layer, Conv2D
from keras import activations, initializers, regularizers, constraints

@keras.saving.register_keras_serializable(package= "Museekar")
class TempConvolution(Layer):
    """
    Temporal Convolution Layer designed for STGCN blocks.
    
    Notes:
    - Applies a 1D convolution over the time dimension independently for each node.
    - Utilizes the Gated Linear Unit (GLU) mechanism standard to STGCN architectures.
    - Expected input shape is `(B, T, N, F_in)`, where B is the batch size, 
      T is the sequence length (time steps), N is the number of nodes, 
      and F_in is the input feature dimension.

    Args:
        units (int): dimensionality of final output feature vectors (GLU halves the internal channels)
        kernel_size (int): length of the 1D convolution window over time
        padding (str): padding mode over the time dimension, typically "valid" or "same"
        activation (str or func, optional): secondary nonlinear activation applied after GLU
        use_bias (bool): toggles an optional bias
        input_dim (int, optional): dimensionality of input features (if input_shape is not provided)
        kernel_initializer (str or func, optional): The initialiser to use for the weights.
        kernel_regularizer (str or func, optional): The regulariser to use for the weights.
        kernel_constraint (str or func, optional): The constraint to use for the weights.
        bias_initializer (str or func, optional): The initialiser to use for the bias.
        bias_regularizer (str or func, optional): The regulariser to use for the bias.
        bias_constraint (str or func, optional): The constraint to use for the bias.
    """

    def __init__(
        self,
        units,
        kernel_size=3,
        padding="valid",
        activation=None,
        use_bias=True,
        input_dim=None,
        kernel_initializer="glorot_uniform",
        kernel_regularizer=None,
        kernel_constraint=None,
        bias_initializer="zeros",
        bias_regularizer=None,
        bias_constraint=None,
        **kwargs,
    ):

        if "input_shape" not in kwargs and input_dim is not None:
            kwargs["input_shape"] = (None, None, input_dim)

        self.units = units
        self.kernel_size = kernel_size
        self.padding = padding
        self.activation = activations.get(activation)
        self.use_bias = use_bias

        self.kernel_initializer = initializers.get(kernel_initializer)
        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.kernel_constraint = constraints.get(kernel_constraint)
        self.bias_initializer = initializers.get(bias_initializer)
        self.bias_regularizer = regularizers.get(bias_regularizer)
        self.bias_constraint = constraints.get(bias_constraint)

        super().__init__(**kwargs)

    def get_config(self):
        """
        Gets class configuration for Keras serialization.
        """
        config = {
            "units": self.units,
            "kernel_size": self.kernel_size,
            "padding": self.padding,
            "use_bias": self.use_bias,
            "activation": activations.serialize(self.activation),
            "kernel_initializer": initializers.serialize(self.kernel_initializer),
            "kernel_regularizer": regularizers.serialize(self.kernel_regularizer),
            "kernel_constraint": constraints.serialize(self.kernel_constraint),
            "bias_initializer": initializers.serialize(self.bias_initializer),
            "bias_regularizer": regularizers.serialize(self.bias_regularizer),
            "bias_constraint": constraints.serialize(self.bias_constraint),
        }
        base_config = super().get_config()
        return {**base_config, **config}

    def compute_output_shape(self, input_shape):
        """
        Computes the output shape of the layer.
        
        Args:
            input_shape: (B, T, N, F_in)
        """
        batch_dim = input_shape[0]
        time_dim = input_shape[1]
        node_dim = input_shape[2]

        if time_dim is not None:
            if self.padding == "valid":
                time_dim = time_dim - self.kernel_size + 1

        return batch_dim, time_dim, node_dim, self.units

    def build(self, input_shape):
        """
        Builds the layer.
        """
        input_dim = int(input_shape[-1])

        # Kernel shape: (time_window, node_window, in_channels, out_channels)
        # GLU requires doubling the output channels (self.units * 2)
        self.conv = Conv2D(
            filters=self.units * 2,
            kernel_size=(self.kernel_size, 1),
            strides=(1, 1),
            padding=self.padding,
            data_format="channels_last",
            use_bias=self.use_bias,
            kernel_initializer=initializers.serialize(self.kernel_initializer),
            kernel_regularizer=regularizers.serialize(self.kernel_regularizer),
            kernel_constraint=constraints.serialize(self.kernel_constraint),
            bias_initializer=initializers.serialize(self.bias_initializer),
            bias_regularizer=regularizers.serialize(self.bias_regularizer),
            bias_constraint=constraints.serialize(self.bias_constraint),
            name="temporal_conv2d",
        )
        self.conv.build(input_shape)
            
        super().build(input_shape)

    def call(self, inputs):
        """
        Applies the temporal convolution layer with GLU.
        """
        # 1. 2D Convolution mapping over Time and Nodes
        output = self.conv(inputs)
            
        # 2. STGCN Gated Linear Unit (GLU) Mechanism
        # Using backend-agnostic exact slicing instead of ops.split to guarantee shape inference 
        P, Q = ops.split(output, 2, axis=-1)
        
        output = P * ops.sigmoid(Q)
        
        # 3. activation
        if self.activation is not None:
            output = self.activation(output)

        return output