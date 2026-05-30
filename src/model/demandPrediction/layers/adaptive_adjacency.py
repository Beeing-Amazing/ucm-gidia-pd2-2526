import keras
from keras import layers, ops

@keras.saving.register_keras_serializable()
class AdaptiveAdjacency(layers.Layer):
    def __init__(self, num_nodes, embed_dim=16, **kwargs):
        super().__init__(**kwargs)
        self.num_nodes = num_nodes
        self.embed_dim = embed_dim

    def build(self, input_shape):
        # Learnable node embeddings
        self.E = self.add_weight(
            shape=(self.num_nodes, self.embed_dim),
            initializer="glorot_uniform",
            name="node_embeddings",
        )
        super().build(input_shape)

    def call(self, inputs):
        # A_learned = softmax(ReLU(E E^T))
        sim = ops.matmul(self.E, ops.transpose(self.E))      # (N, N)
        sim = ops.relu(sim)
        A_learned = ops.softmax(sim, axis=-1)
        return A_learned  # shape (N, N)
    def compute_output_shape(self, input_shape):
        return (self.num_nodes, self.num_nodes)
    
    def get_config(self):
        config = super().get_config()
        config.update({
            "num_nodes": self.num_nodes,
            "embed_dim": self.embed_dim
        })
        return config