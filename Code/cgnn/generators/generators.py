""" Regression and generation functions
Author: Diviyan Kalainathan & Olivier Goudet
Date : 30/06/17
"""
import numpy as np
import tensorflow as tf
from sklearn.linear_model import LassoLars
from sklearn.svm import SVR

from Code.cgnn.CGNN import CGNN_tf as CGNN
from ..utils.Loss import MMD_loss_tf as MMD
from ..utils.Settings import SETTINGS


def init(size):
    """ Initialize a random tensor, normal(0,SETTINGS.init_weights).
        :param size: Size of the tensor
        :return: Tensor
    """
    return tf.random_normal(shape=size, stddev=SETTINGS.init_weights)


class FullGraphPolynomialModel_tf(object):
    def __init__(self, N, graph, list_nodes, run=0, idx=0, **kwargs):
        """ Build the tensorflow graph of the 2nd-degree Polynomial generator structure

        :param N: Number of points
        :param graph: Graph to be run
        :param run: number of the run (only for log)
        :param idx: number of the idx (only for log)
        :param kwargs: learning_rate=(SETTINGS.learning_rate) learning rate of the optimizer

        """
        super(FullGraphPolynomialModel_tf, self).__init__()
        learning_rate = kwargs.get('learning_rate', SETTINGS.learning_rate)

        self.run = run
        self.idx = idx
        n_var = len(list_nodes)

        self.all_real_variables = tf.placeholder(tf.float32, shape=[None, n_var])
        alpha = tf.Variable(init([1, 1]))
        generated_variables = {}
        theta_G = [alpha]

        while len(generated_variables) < n_var:
            for var in list_nodes:
                # Check if all parents are generated
                par = graph.get_parents(var)

                if (var not in generated_variables and
                        set(par).issubset(generated_variables)):

                    # Generate the variable
                    W_in = tf.Variable(init([int((len(par) + 2) * (len(par) + 1) / 2), 1]))

                    input_v = []
                    input_v.append(tf.ones([N, 1]))
                    for i in par:
                        input_v.append(generated_variables[i]/((len(par) + 2) * (len(par) + 1) / 2))
                        # Renormalize w/ number of inputs?
                    input_v.append(tf.random_normal([N, 1], mean=0, stddev=1))

                    out_v = 0
                    cpt = 0
                    for i in range(len(par) + 2):
                        for j in range(i + 1, len(par) + 2):
                            out_v += W_in[cpt] * tf.multiply(input_v[i], input_v[j])
                            cpt += 1

                    generated_variables[var] = out_v
                    theta_G.extend([W_in])

        listvariablegraph = []
        for var in list_nodes:
            listvariablegraph.append(generated_variables[var])

        self.all_generated_variables = tf.concat(listvariablegraph, 1)
        self.G_dist_loss_xcausesy = MMD(self.all_real_variables, self.all_generated_variables)

        # var_list = theta_G
        self.G_solver_xcausesy = (tf.train.AdamOptimizer(
            learning_rate=learning_rate).minimize(self.G_dist_loss_xcausesy,
                                                  var_list=theta_G))

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True

        self.sess = tf.Session(config=config)
        self.sess.run(tf.global_variables_initializer())

    def train(self, data, verbose=True, **kwargs):
        """ Train the polynomial model by fitting on data using MMD

        :param data: data to fit
        :param verbose: verbose
        :param kwargs: train_epochs=(SETTINGS.nb_epoch_train) number of train epochs
        :return: Train loss at the last epoch
        """
        train_epochs = kwargs.get('train_epochs', SETTINGS.train_epochs)
        for it in range(train_epochs):
            _, G_dist_loss_xcausesy_curr = self.sess.run(
                [self.G_solver_xcausesy, self.G_dist_loss_xcausesy],
                feed_dict={self.all_real_variables: data}
            )

            if verbose:
                if it % 10 == 0:
                    print('Pair:{}, Run:{}, Iter:{}, score:{}'.
                          format(self.idx, self.run,
                                 it, G_dist_loss_xcausesy_curr))

        return G_dist_loss_xcausesy_curr

    def evaluate(self, data, verbose=True):
        """ Run the model to generate data and output

        :param data: input data
        :param verbose: verbose
        :return: Generated data
        """

        sumMMD_tr = 0

        for it in range(1):

            MMD_tr, generated_variables = self.sess.run([self.G_dist_loss_xcausesy,
                                                         self.all_generated_variables],
                                                        feed_dict={self.all_real_variables: data})
            if verbose:
                print('Pair:{}, Run:{}, Iter:{}, score:{}'.format(self.idx, self.run, it, MMD_tr))

        tf.reset_default_graph()

        return generated_variables


def full_graph_polynomial_generator_tf(df_data, graph, idx=0, run=0, **kwargs):
    """ Run the full graph polynomial generator

    :param df_data: data
    :param graph: the graph to model
    :param idx: index (optional, for log purposes)
    :param run: no of run (optional, for log purposes)
    :param kwargs: gpu=(SETTINGS.GPU) True if GPU is used
    :param kwargs: nb_gpu=(SETTINGS.NB_GPU) Number of available GPUs
    :param kwargs: gpu_offset=(SETTINGS.GPU_OFFSET)number of gpu offsets
    :return: Generated data using the graph structure
    """

    gpu = kwargs.get('gpu', SETTINGS.GPU)
    nb_gpu = kwargs.get('nb_gpu', SETTINGS.NB_GPU)
    gpu_offset = kwargs.get('gpu_offset', SETTINGS.GPU_OFFSET)

    list_nodes = graph.get_list_nodes()
    print(list_nodes)
    data = df_data[list_nodes].as_matrix()
    data = data.astype('float32')

    if gpu:
        with tf.device('/gpu:' + str(gpu_offset + run % nb_gpu)):

            model = FullGraphPolynomialModel_tf(df_data.shape[0], graph, list_nodes, run, idx, **kwargs)
            loss = model.train(data, **kwargs)/()
            if np.isfinite(loss):
                return model.evaluate(data)
            else:
                print('Has not converged, re-running graph inference')
                return full_graph_polynomial_generator_tf(df_data, graph, **kwargs)

    else:
        model = FullGraphPolynomialModel_tf(len(df_data), graph, list_nodes, run, idx, **kwargs)
        loss = model.train(data, **kwargs)
        if np.isfinite(loss):
            return model.evaluate(data)
        else:
            print('Has not converged, re-running graph inference')
            return full_graph_polynomial_generator_tf(df_data, graph, **kwargs)


def CGNN_generator_tf(df_data, graph, idx=0, run=0, **kwargs):
    """ Run the full graph polynomial generator

    :param df_data: data
    :param graph: the graph to model
    :param idx: index (optional, for log purposes)
    :param run: no of run (optional, for log purposes)
    :param kwargs: gpu=(SETTINGS.GPU) True if GPU is used
    :param kwargs: nb_gpu=(SETTINGS.NB_GPU) Number of available GPUs
    :param kwargs: gpu_offset=(SETTINGS.GPU_OFFSET) number of gpu offsets
    :return: Generated data using the graph structure
    """

    gpu = kwargs.get('gpu', SETTINGS.GPU)
    nb_gpu = kwargs.get('nb_gpu', SETTINGS.NB_GPU)
    gpu_offset = kwargs.get('gpu_offset', SETTINGS.GPU_OFFSET)

    list_nodes = graph.get_list_nodes()
    print(list_nodes)
    data = df_data[list_nodes].as_matrix()
    data = data.astype('float32')

    if gpu:
        with tf.device('/gpu:' + str(gpu_offset + run % nb_gpu)):

            model = CGNN(df_data.shape[0], graph, run, idx, h_layer_dim=3, **kwargs)
            loss = model.train(data, **kwargs)
            return model.generate(data)

    else:
        model = CGNN(len(df_data), graph, run, idx, **kwargs)
        loss = model.train(data, **kwargs)
        return model.generate(data)




def polynomial_regressor(x, target, causes, fixed_noise=False, verbose=True, **kwargs):
    """ Regress data using a polynomial regressor of degree 2

    :param x: parents data
    :param target: target data
    :param causes: list of parent nodes
    :param train_epochs: number of train epochs
    :param fixed_noise : If the noise in the generation is fixed or not.
    :param verbose: verbose
    :return: generated data
    """

    lr = kwargs.get('learning_rate', SETTINGS.learning_rate)
    train_epochs = kwargs.get('train_epochs', SETTINGS.train_epochs)
    n_ex = target.shape[0]
    if len(causes) == 0:
        causes = []
        x = None
        if fixed_noise:
            x_input = th.FloatTensor(n_ex, 1).normal_()
    elif fixed_noise:
        x = th.FloatTensor(x)
        x_input = th.cat([x, th.FloatTensor(n_ex, 1).normal_()], 1)
    else:
        x_input = th.FloatTensor(x)
    target = Variable(th.FloatTensor(target))
    model = PolynomialModel(len(causes), degree=2)
    if SETTINGS.GPU:
        model.cuda()
        target.cuda()
        if x_input is not None:
            x_input.cuda()
    criterion = MomentMatchingLoss(4)
    optimizer = th.optim.Adam(model.parameters(), lr=lr)

    for epoch in range(train_epochs):
        optimizer.zero_grad()
        y_tr = model(x_input, n_ex, fixed_noise=fixed_noise)
        x = Variable(x_input)
        loss = criterion(th.cat([y_tr, x], 1), th.cat([target.resize(target.size()[0], 1), x], 1))
        loss.backward()
        optimizer.step()

        if verbose and epoch % 50 == 0:
            print('Epoch : {} ; Loss: {}'.format(epoch, loss.data.numpy()))

    return model(x_input, n_ex).data.numpy()


def linear_regressor(x, target, causes):
    """ Regression and prediction using a lasso

    :param x: data
    :param target: target - effect
    :param causes: causes of the causal mechanism
    :return: regenerated data with the fitted model
    """

    if len(causes) == 0:
        x= np.random.normal(size=(target.shape[0], 1))

    lasso = LassoLars(alpha=1.)  # no regularization
    lasso.fit(x, target)

    return lasso.predict(x)


def support_vector_regressor(x, target, causes):
    """ Regression and prediction using a SVM (rbf)

    :param x: data
    :param target: target - effect
    :param causes: causes of the causal mechanism
    :return: regenerated data with the fitted model
    """
    svr_rbf = SVR(kernel='rbf', C=1e3, gamma=0.1)
    if len(causes) == 0:
        x = np.random.normal(size=(target.shape[0], 1))

    return svr_rbf.fit(x, target).predict(x)

