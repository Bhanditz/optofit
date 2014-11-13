import numpy as np
# Set the random seed for reproducibility
seed = np.random.randint(2**16)

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from optofit.cneuron.compartment import Compartment
from optofit.cneuron.channels import LeakChannel
from optofit.cneuron.simulate import forward_euler
from optofit.cneuron.gpchannel import GPChannel, sigma

from hips.inference.particle_mcmc import *
from optofit.cinference.pmcmc import *

# Make a simple compartment
hypers = {
            'C'      : 1.0,
            'V0'     : -60.0,
            'g_leak' : 0.3,
            'E_leak' : -65.0,
            'g_gp'   : 1.0,
            'E_gp'   : 0.0,
         }

print "Seed: ", seed
np.random.seed(seed)

def plot_state(z, axs=None, I=None, color='k'):
    if axs is None:
        fig = plt.figure()
        ax1 = fig.add_subplot(311)
        ax2 = fig.add_subplot(312)
        ax3 = fig.add_subplot(313)

    # Plot the voltage
    ax1.plot(t, z[:,0], color=color)
    # ax1.plot(t, x[:,0],  'r')
    ax1.set_ylabel('V')

    ax2.plot(t, sigma(z[:,1]), color=color)
    ax2.set_ylabel('\\sigma(z_1)')
    ax2.set_ylim((0,1))

    if I is not None:
        ax3.plot(t, I, color=color)
        ax3.set_ylabel('I_{gp}')
        ax3.set_xlabel('t')

def sample_model():
    # Add a few channels
    body = Compartment(name='body', hypers=hypers)
    leak = LeakChannel(name='leak', hypers=hypers)
    gp = GPChannel(name='gp', hypers=hypers)

    gp.plot()

    body.add_child(leak)
    body.add_child(gp)
    # Initialize the model
    D, I = body.initialize_offsets()

    # Set the recording duration
    t_start = 0
    t_stop = 100.
    dt = 1.0
    t = np.arange(t_start, t_stop, dt)
    T = len(t)

    # Make input with an injected current from 500-600ms
    inpt = np.zeros((T, I))
    inpt[50/dt:60/dt,:] = 7.
    inpt += np.random.randn(T, I)

    # Set the initial distribution to be Gaussian around the steady state
    z0 = np.zeros(D)
    body.steady_state(z0)
    init = GaussianInitialDistribution(z0, 0.1**2 * np.eye(D))

    # Set the proposal distribution using Hodgkin Huxley dynamics
    # TODO: Fix the hack which requires us to know the number of particles
    N = 1
    sigmas = 0.0001*np.ones(D)
    # Set the voltage transition dynamics to be a bit noisier
    sigmas[body.x_offset] = 0.25
    prop = HodgkinHuxleyProposal(T, N, D, body,  sigmas, t, inpt)

    # Set the observation model to observe only the voltage
    etas = np.ones(1)
    observed_dims = np.array([body.x_offset]).astype(np.int32)
    lkhd = PartialGaussianLikelihood(observed_dims, etas)

    # Initialize the latent state matrix to sample N=1 particle
    z = np.zeros((T,N,D))
    z[0,0,:] = init.sample()
    # Initialize the output matrix
    x = np.zeros((T,D))

    # Sample the latent state sequence
    for i in np.arange(0,T-1):
        # The interface kinda sucks. We have to tell it that
        # the first particle is always its ancestor
        prop.sample_next(z, i, np.array([0], dtype=np.int32))

    # Sample observations
    for i in np.arange(0,T):
        lkhd.sample(z,x,i,0)

    # Extract the GP current
    I_gp = gp.current(z, z[:,0,0], np.arange(T), 0)

    # Extract the first (and in this case only) particle
    z = z[:,0,:].copy(order='C')


    # Plot the first particle trajectory
    # fig = plt.figure()
    # ax1 = fig.add_subplot(311)
    # ax1.plot(t, z[:,observed_dims[0]], 'k')
    # ax1.plot(t, x[:,0],  'r')
    # ax1.set_ylabel('V')
    #
    # ax2 = fig.add_subplot(312)
    # ax2.plot(t, sigma(z[:,1]), 'k')
    # ax2.set_ylabel('\\sigma(z_1)')
    # ax2.set_ylim((0,1))
    #
    # ax3 = fig.add_subplot(313)
    # ax3.plot(t, I_gp, 'k')
    # ax3.set_ylabel('I_{gp}')
    # ax3.set_xlabel('t')
    plot_state(z, I=I_gp, color='k')
    plt.ion()
    plt.show()
    plt.pause(0.01)

    return t, z, x, init, prop, lkhd

# Now run the pMCMC inference
def sample_z_given_x(t, z_curr, x,
                     init, prop, lkhd,
                     N_particles=100,
                     plot=False,
                     axs=None):

    T,D = z_curr.shape
    T,O = x.shape
    # import pdb; pdb.set_trace()
    pf = ParticleGibbsAncestorSampling(T, N_particles, D)
    pf.initialize(init, prop, lkhd, x, z_curr)

    S = 100
    z_smpls = np.zeros((S,T,D))
    l = plt.plot(t, z_smpls[0,:,0], 'b')
    for s in range(S):
        print "Iteration %d" % s
        # Reinitialize with the previous particle
        pf.initialize(init, prop, lkhd, x, z_smpls[s,:,:])
        z_smpls[s,:,:] = pf.sample()
        l[0].set_data(t, z_smpls[s,:,0])
        plt.pause(0.01)

    z_mean = z_smpls.mean(axis=0)
    z_std = z_smpls.std(axis=0)
    z_env = np.zeros((T*2,2))

    z_env[:,0] = np.concatenate((t, t[::-1]))
    z_env[:,1] = np.concatenate((z_mean[:,0] + z_std[:,0], z_mean[::-1,0] - z_std[::-1,0]))

    if plot:
        plt.gca().add_patch(Polygon(z_env, facecolor='b', alpha=0.25, edgecolor='none'))
        # plt.plot(t, z_mean[:,0], 'b', lw=1)

        # Compute the current
        plot_state(z_mean, axs=axs, color='b')

        # Plot a few random samples
        # for s in range(10):
        #     si = np.random.randint(S)
        #     plt.plot(t, z_smpls[si,:,0], '-b', lw=0.5)

        plt.ioff()
        plt.show()

    return z_smpls

t, z, x, init, prop, lkhd = sample_model()
sample_z_given_x(t, z, x, init, prop, lkhd, plot=True)