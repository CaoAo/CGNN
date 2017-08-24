"""
GNN : Generative Neural Networks for causal inference (pairwise)
Authors : Olivier Goudet & Diviyan Kalainathan
Ref:
Date : 10/05/2017
"""
import os
import tensorflow as tf

#os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import numpy as np
from ...utils.Loss import MMD_loss_tf as MMD_tf
from ...utils.Loss import Fourier_MMD_Loss_tf as Fourier_MMD_tf
from ...utils.Settings import SETTINGS
from joblib import Parallel, delayed
from sklearn.preprocessing import scale
from .model import Pairwise_Model
import pandas as pd

def init(size, **kwargs):
    """ Initialize a random tensor, normal(0,kwargs(SETTINGS.init_weights)).

    :param size: Size of the tensor
    :param kwargs: init_std=(SETTINGS.init_weights) Std of the initialized normal variable
    :return: Tensor
    """
    init_std = kwargs.get('init_std', SETTINGS.init_weights)
    return tf.random_normal(shape=size, stddev=init_std)


class GNN_tf(object):
    def __init__(self, N, run=0, pair=0, **kwargs):
        """ Build the tensorflow graph, the first column is set as the cause and the second as the effect

        :param N: Number of examples to generate
        :param run: for log purposes (optional)
        :param pair: for log purposes (optional)
        :param kwargs: h_layer_dim=(SETTINGS.h_layer_dim) Number of units in the hidden layer
        :param kwargs: learning_rate=(SETTINGS.learning_rate) learning rate of the optimizer
        :param kwargs: use_Fast_MMD=(SETTINGS.use_Fast_MMD) use fast MMD option
        :param kwargs: nb_vectors_approx_MMD=(SETTINGS.nb_vectors_approx_MMD) nb vectors
        """

        h_layer_dim = kwargs.get('h_layer_dim', SETTINGS.h_layer_dim)
        learning_rate = kwargs.get('learning_rate', SETTINGS.learning_rate)
        use_Fast_MMD = kwargs.get('use_Fast_MMD', SETTINGS.use_Fast_MMD)
        nb_vectors_approx_MMD = kwargs.get('nb_vectors_approx_MMD', SETTINGS.nb_vectors_approx_MMD)

        self.run = run
        self.pair = pair
        self.X = tf.placeholder(tf.float32, shape=[None, 1])
        self.Y = tf.placeholder(tf.float32, shape=[None, 1])

        #Ws_in = tf.Variable(init([1, h_layer_dim], **kwargs))
        #bs_in = tf.Variable(init([h_layer_dim], **kwargs))
        #Ws_out = tf.Variable(init([h_layer_dim, 1], **kwargs))
        #bs_out = tf.Variable(init([1], **kwargs))

        W_in = tf.Variable(init([2, h_layer_dim], **kwargs))
        b_in = tf.Variable(init([h_layer_dim], **kwargs))
        W_out = tf.Variable(init([h_layer_dim, 1], **kwargs))
        b_out = tf.Variable(init([1], **kwargs))

        #theta_G = [W_in, b_in,
        #           W_out, b_out,
        #           Ws_in, bs_in,
        #           Ws_out, bs_out]

        theta_G = [W_in, b_in,
                   W_out, b_out]


        #es = tf.random_normal([N, 1], mean=0, stddev=1)
        #
        #out_x = tf.nn.relu(tf.matmul(es, Ws_in) + bs_in)
        #out_x = tf.matmul(out_x, Ws_out) + bs_out

        e = tf.random_normal([N, 1], mean=0, stddev=1)

        hid = tf.nn.relu(tf.matmul(tf.concat([self.X, e], 1), W_in) + b_in)
        out_y = tf.matmul(hid, W_out) + b_out

        if(use_Fast_MMD):
            self.G_dist_loss_xcausesy = Fourier_MMD_tf(tf.concat([self.X, self.Y], 1), tf.concat([self.X, out_y], 1), nb_vectors_approx_MMD)
        else:
            self.G_dist_loss_xcausesy = MMD_tf(tf.concat([self.X, self.Y], 1), tf.concat([self.X, out_y], 1))

        self.G_solver_xcausesy = (tf.train.AdamOptimizer(learning_rate=learning_rate)
                                  .minimize(self.G_dist_loss_xcausesy, var_list=theta_G))

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        self.sess = tf.Session(config=config)
        self.sess.run(tf.global_variables_initializer())

    def train(self, data, verbose=True, **kwargs):
        """ Train the GNN model

        :param data: data corresponding to the graph
        :param verbose: verbose
        :param kwargs: train_epochs=(SETTINGS.nb_epoch_train) number of train epochs
        :return: None
        """
        train_epochs = kwargs.get('train_epochs', SETTINGS.train_epochs)

        for it in range(train_epochs):
            _, G_dist_loss_xcausesy_curr = self.sess.run(
                [self.G_solver_xcausesy, self.G_dist_loss_xcausesy],
                feed_dict={self.X: data[:, [0]], self.Y: data[:, [1]]}
            )

            if verbose:
                if it % 100 == 0:
                    print('Pair:{}, Run:{}, Iter:{}, score:{}'.
                          format(self.pair, self.run,
                                 it, G_dist_loss_xcausesy_curr))

    def evaluate(self, data, verbose=True, **kwargs):
        """ Test the model

        :param data: data corresponding to the graph
        :param verbose: verbose
        :param kwargs: test_epochs=(SETTINGS.nb_epoch_test) number of test epochs
        :return: mean MMD loss value of the CGNN structure on the data
        """
        test_epochs = kwargs.get('test_epochs', SETTINGS.test_epochs)
        avg_score = 0

        for it in range(test_epochs):
            score = self.sess.run([self.G_dist_loss_xcausesy], feed_dict={self.X: data[:, [0]], self.Y: data[:, [1]]})

            avg_score += score[0]

            if verbose:
                if it % 100 == 0:
                    print('Pair:{}, Run:{}, Iter:{}, score:{}'.format(self.pair, self.run, it, score[0]))

        tf.reset_default_graph()

        return avg_score / test_epochs


def tf_evalcausalscore_pairwise(df, idx, run, **kwargs):
    GNN = GNN_tf(df.shape[0], run, idx, **kwargs)
    GNN.train(df, **kwargs)
    return GNN.evaluate(df, **kwargs)


def tf_run_instance(m, idx, run, **kwargs):
    """ Execute the CGNN, by init, train and eval either on CPU or GPU

    :param m: data corresponding to the config : (N, 2) data, [:, 0] cause and [:, 1] effect
    :param run: number of the run (only for print)
    :param idx: number of the idx (only for print)
    :param kwargs: gpu=(SETTINGS.GPU) True if GPU is used
    :param kwargs: nb_gpu=(SETTINGS.NB_GPU) Number of available GPUs
    :param kwargs: gpu_offset=(SETTINGS.GPU_OFFSET) number of gpu offsets
    :return: MMD loss value of the given structure after training
    """
    gpu = kwargs.get('gpu', SETTINGS.GPU)
    nb_gpu = kwargs.get('nb_gpu', SETTINGS.NB_GPU)
    gpu_offset = kwargs.get('gpu_offset', SETTINGS.GPU_OFFSET)

    if (m.shape[0] > SETTINGS.max_nb_points):

        p = np.random.permutation(m.shape[0])
        m = m[p[:int(SETTINGS.max_nb_points)],:]
 


    run_i = run
    if gpu:
        with tf.device('/gpu:' + str(gpu_offset + run_i % nb_gpu)):
            XY = tf_evalcausalscore_pairwise(m, idx, run, **kwargs)
        with tf.device('/gpu:' + str(gpu_offset + run_i % nb_gpu)):
            YX = tf_evalcausalscore_pairwise(m[:, [1, 0]], idx, run, **kwargs)
            return [XY, YX]
    else:
        return [tf_evalcausalscore_pairwise(m, idx, run, **kwargs),
                tf_evalcausalscore_pairwise(np.fliplr(m), idx, run, **kwargs)]



class GNN(Pairwise_Model):
    """
    Shallow Generative Neural networks, models the causal directions x->y and y->x with a 1-hidden layer neural network
    and a MMD loss. The causal direction is considered as the "best-fit" between the two directions
    """

    def __init__(self, backend="PyTorch"):
        super(GNN, self).__init__()
        self.backend = backend

    def predict_proba(self, a, b,idx=0, **kwargs):

        backend_alg_dic = {"TensorFlow": tf_run_instance}
        if len(np.array(a).shape) == 1:
            a = np.array(a).reshape((-1, 1))
            b = np.array(b).reshape((-1, 1))

        nb_jobs = kwargs.get("nb_jobs", SETTINGS.NB_JOBS)
        nb_runs = kwargs.get("nb_runs", SETTINGS.NB_RUNS)
        m = np.hstack((a, b))
        m = m.astype('float32')
        

        result_pair = Parallel(n_jobs=nb_jobs)(delayed(backend_alg_dic[self.backend])(
            m, idx, run, **kwargs) for run in range(nb_runs))
     
        score_AB = np.mean([runpair[0] for runpair in result_pair])
        score_BA = np.mean([runpair[1] for runpair in result_pair])
        
        for runpair in result_pair:
            print(runpair[0])
        print(score_AB)

        for runpair in result_pair:
            print(runpair[1])
        print(score_BA)

        return (score_BA - score_AB) / (score_BA + score_AB)
