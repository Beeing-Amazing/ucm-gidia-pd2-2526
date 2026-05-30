import keras
from keras import ops 
from keras.layers import Layer
from keras import activations, initializers, regularizers, constraints
#import tensorflow as tf # Tensorflow is only used for Sparse Adjacency Matriz, we don't plan to use that

@keras.saving.register_keras_serializable(package= "Museekar")
class GraphConvolution(Layer):

    """
    Graph Convolution (GCN) Keras layer.
    The implementation is based on https://github.com/stellargraph/stellargraph.

    Notes:
      - The batch axis represents independent graphs to be convolved with this GCN kernel (for
        instance, for full-batch node prediction on a single graph, its dimension should be 1).

      - If the adjacency matrix is dense, both it and the features should have a batch axis, with
        equal batch dimension.

      - There are two inputs required, the node features,
        and the graph Laplacian matrix

      - This class assumes that the normalized Laplacian matrix is passed as
        input to the Keras methods.

    .. seealso:: :class:`.GCN` combines several of these layers.

    Args:
        units (int): dimensionality of output feature vectors
        activation (str or func): nonlinear activation applied to layer's output to obtain output features
        use_bias (bool): toggles an optional bias
        final_layer (bool): Deprecated, use ``tf.gather`` or :class:`.GatherIndices`
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
        activation=None,
        use_bias=True,
        final_layer=None,
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
            kwargs["input_shape"] = (input_dim,)

        self.units = units
        self.activation = activations.get(activation)
        self.use_bias = use_bias
        if final_layer is not None:
            raise ValueError(
                "'final_layer' is not longer supported, use 'tf.gather' or 'GatherIndices' separately"
            )

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
        Used by Keras model serialization.

        Returns:
            A dictionary that contains the config of the layer
        """

        config = {
            "units": self.units,
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

    def compute_output_shape(self, input_shapes):
        """
        Computes the output shape of the layer.
        Assumes the following inputs:

        Args:
            input_shapes:
            - features: (B, T, N, F_in)
            - adjacency: (N, N) or (B, N, N) [ignored for shape]

        Returns:
            An input shape tuple.
        """
        feature_shape, *As_shapes = input_shapes

        batch_dim = feature_shape[0]
        time_dim = feature_shape[1]
        node_dim = feature_shape[2]

        return batch_dim, time_dim, node_dim, self.units


    def build(self, input_shapes):
        """
        Builds the layer

        Args:
            input_shapes (list of int): shapes of the layer's inputs (node features and adjacency matrix)

        """
        feat_shape = input_shapes[0]
        input_dim = int(feat_shape[-1])

        self.kernel = self.add_weight(
            shape=(input_dim, self.units),
            initializer=self.kernel_initializer,
            name="kernel",
            regularizer=self.kernel_regularizer,
            constraint=self.kernel_constraint,
        )

        if self.use_bias:
            self.bias = self.add_weight(
                shape=(self.units,),
                initializer=self.bias_initializer,
                name="bias",
                regularizer=self.bias_regularizer,
                constraint=self.bias_constraint,
            )
        else:
            self.bias = None
        super().build(input_shapes)


    def call(self, inputs):
        """
        Applies the layer.

        Args:
            inputs (list): a list of 3 input tensors that includes
                node features (size T x N x F),
                graph adjacency matrix (size N x N),
                where N is the number of nodes in the graph, and
                F is the dimensionality of node features.

        Returns:
            Keras Tensor that represents the output of the layer.
        """
        features, *As = inputs

        # Calculate the layer operation of GCN
        A = As[0]
        """ The following is disabled so the code can be executed regardless of the backend
        if isinstance(A, tf.SparseTensor):
            # FIXME(#1222): batch_dot doesn't support sparse tensors, so we special case them to
            # only work with a single batch element (and the adjacency matrix without a batch
            # dimension)
            if features.shape[0] != 1:
                raise ValueError(
                    f"features: expected batch dimension = 1 when using sparse adjacency matrix in GraphConvolution, found features batch dimension {features.shape[0]}"
                )
            if len(A.shape) != 2:
                raise ValueError(
                    f"adjacency: expected a single adjacency matrix when using sparse adjacency matrix in GraphConvolution (tensor of rank 2), found adjacency tensor of rank {len(A.shape)}"
                )
        
            features_sq = ops.squeeze(features, axis=0)
            h_graph = tf.sparse.sparse_dense_matmul(A, features_sq)
            h_graph = ops.expand_dims(h_graph, axis=0)
        else:
            h_graph = ops.matmul(A, features)
        """
        # If A has no batch dim: (N, N) -> broadcast to (batch, N, N) in einsum
        # Spatial graph conv at each time step:
        # A: (n, n) or (b, n, n)
        # features: (b, t, n, f)
        # h_graph: (b, t, n, f)
        if len(A.shape) == 2: 
            # shared A for all batches
            h_graph = ops.einsum("nm,btmf->btnf", A, features)
        else:
            # batched A
            h_graph = ops.einsum("bnm,btmf->btnf", A, features)

        # h_graph: (b, t, n, f), kernel: (f, u) -> output: (b, t, n, u)
        output = ops.einsum("btnf,fu->btnu", h_graph, self.kernel)
        
        # Add optional bias & apply activation
        if self.bias is not None:
            output += self.bias
        if self.activation is not None:
            output = self.activation(output)

        return output
