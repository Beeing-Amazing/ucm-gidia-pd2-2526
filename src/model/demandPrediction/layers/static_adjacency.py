import keras
from keras import layers, ops

@keras.saving.register_keras_serializable()
class StaticAdjacency(layers.Layer):
    """
    A layer that holds a static Adjacency matrix.
    Passes the matrix down to GCN blocks.

    You need to set the matrix with set_weights([Adjacency matrix])
    """
    def __init__(self, num_nodes,**kwargs):
        super().__init__(**kwargs)
        self.num_nodes = num_nodes
    def build(self, input_shape):
        self.A = self.add_weight(
            shape=(self.num_nodes, self.num_nodes),
            initializer="zeros", 
            trainable=False,
            name="static_adjacency"
        )
        super().build(input_shape)

    def call(self, inputs):
        return self.A
    
    def compute_output_shape(self, input_shape):
        return (self.num_nodes, self.num_nodes)
    
    def get_config(self):
        config = super().get_config()
        config.update({
            "num_nodes": self.num_nodes,
        })
        return config