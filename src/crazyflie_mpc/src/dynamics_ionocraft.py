# ----------------------------------------------------------------------------------------------------------------------



# Start importing packages
import numpy as np
import math
from dynamics import *

__author__ = 'Nathan Lambert'
__version__ = '0.1'

class IonoCraft(Dynamics):
    def __init__(self, dt, threeinput = True, m=67e-6, L=.01, Ixx = 5.5833e-10, Iyy = 5.5833e-10, Izz = 1.1167e-09, angle = 0, x_noise = .0001, u_noise=0, linear = False):

        # manually declares the state dicts for these options

        # Each state correspondends to the instance in the state updates. The type of state will correspond to the normalization and how it is passed into the neural net. This is mostly so the NN class can automatically scale the angles and add elements of sin and cosine of each element. In the future, may help other things as well.
        _state_dict = {
                    'X': [0, 'pos'],
                    'Y': [1, 'pos'],
                    'Z': [2, 'pos'],
                    'vx': [3, 'vel'],
                    'vy': [4, 'vel'],
                    'vz': [5, 'vel'],
                    'yaw': [6, 'angle'],
                    'pitch': [7, 'angle'],
                    'roll': [8, 'angle'],
                    'w_x': [9, 'omega'],
                    'w_y': [10, 'omega'],
                    'w_z': [11, 'omega'],
                    'ax': [12, 'accel'],
                    'ay': [13, 'accel'],
                    'az': [14, 'accel']
                    }

        # user can pass a list of items they want to train on in the neural net, eg learn_list = ['vx', 'vy', 'vz', 'yaw'] and iterate through with this dictionary to easily stack data

        # input dictionary less likely to be used because one will not likely do control without a type of acutation. Could be interesting though
        if threeinput:
            _input_dict = {
                        'Thrust': [0, 'force'],
                        'taux': [1, 'torque'],
                        'tauy': [2, 'torque']
                        }
        else:
            _input_dict = {
                    'F1': [0, 'force'],
                    'F2': [1, 'force'],
                    'F3': [2, 'force'],
                    'F4': [3, 'force']
                    }

        super().__init__(_state_dict, _input_dict, dt, x_dim=len(_state_dict), u_dim=len(_input_dict), x_noise = x_noise, u_noise=u_noise)

        # Setup the state indices
        self.idx_xyz = [0, 1, 2]
        self.idx_xyz_dot = [3, 4, 5]
        self.idx_ptp = [6, 7, 8]
        self.idx_ptp_dot = [9, 10, 11]
        self.idx_xyz_ddot = [12, 13, 14]

        # Setup the parameters
        self.m = m
        self.L = L
        self.threeinput = threeinput
        self.angle = angle
        self.Ixx = Ixx
        self.Iyy = Iyy
        self.Izz = Izz
        self.g = 9.81
        self.Ib = np.array([
            [Ixx, 0, 0],
            [0, Iyy, 0],
            [0, 0, Izz]
        ])

        # Defines equilibrium control for the IonoCraft
        if threeinput:
            self.u_e = np.array([m*self.g, 0, 0])
        else:
            self.u_e = (m*self.g/4)*np.ones(4)

        # Hover control matrices
        self._hover_mats = [np.array([1, 1, 1, 1]),      # z
                            np.array([-1, -1, 1, 1]),   # pitch
                            np.array([-1, 1, 1, -1])]   # roll

    def _enforce_input_range(self, input, lowerbound = 0, upperbound = 500e-6):
        # enforces the max and min of an input to an ionocraft
        # input is a 4x1 vect
        return np.clip(input, lowerbound, upperbound)

    def force2thrust_torque(self, angle):
        # transformation matrix for ionocraft with XY thrusts
        # [Thrustx; Thrusty; Thrustz; Tauz; Tauy; Taux;] = M * [F4; F3; F2; F1]
        M =  np.array([[0.,         math.sin(angle),           0.,                     -math.sin(angle)],
                    [-math.sin(angle),         0.,                        math.sin(angle),           0.],
                    [math.cos(angle),          math.cos(angle),           math.cos(angle),           math.cos(angle)],
                    [-self.L*math.sin(angle),  self.L*math.sin(angle),    -self.L*math.sin(angle),   self.L*math.sin(angle)],
                    [-self.L*math.cos(angle),  -self.L*math.cos(angle),   self.L*math.cos(angle),    self.L*math.cos(angle)],
                    [self.L*math.cos(angle),   -self.L*math.cos(angle),   -self.L*math.cos(angle),   self.L*math.cos(angle)]])
        return M

    def pqr2rpy(self, x0, pqr):
        rotn_matrix = np.array([[1., math.sin(x0[0]) * math.tan(x0[1]), math.cos(x0[0]) * math.tan(x0[1])],
                                [0., math.cos(x0[0]),                   -math.sin(x0[0])],
                                [0., math.sin(x0[0]) / math.cos(x0[1]), math.cos(x0[0]) / math.cos(x0[1])]])

        return rotn_matrix.dot(pqr)

    def simulate(self, x, u, t=None):
        self._enforce_dimension(x, u)
        dt = self.dt
        u0 = u
        x0 = x
        idx_xyz = self.idx_xyz
        idx_xyz_dot = self.idx_xyz_dot
        idx_ptp = self.idx_ptp
        idx_ptp_dot = self.idx_ptp_dot
        idx_xyz_ddot = self.idx_xyz_ddot

        m = self.m
        L = self.L
        angle = self.angle
        Ixx = self.Ixx
        Iyy = self.Iyy
        Izz = self.Izz
        Ib = self.Ib
        g = self.g

        # Easy access to yawpitchroll vector
        ypr = x0[idx_ptp]

        # Add noise to input
        u_noise_vec = np.random.normal(loc=0, scale = self.u_noise, size=(self.u_dim))
        u = u+u_noise_vec

        # if 3 dimensional input, tranform to thruster form
        if self.threeinput:
            u = (u[0]/4)*self._hover_mats[0]+(u[1]*L/4)*self._hover_mats[1]+(u[2]*L/4)*self._hover_mats[2]

        # enforce dimensions
        u = self._enforce_input_range(u)

        # Transform the input into body frame forces
        T_tau_thrusters = np.zeros(6)
        T_tau_thrusters = np.matmul(self.force2thrust_torque(angle),u)
        Tx = T_tau_thrusters[0]
        Ty = T_tau_thrusters[1]
        Tz = T_tau_thrusters[2]
        Tauz = T_tau_thrusters[3]
        Tauy = T_tau_thrusters[4]
        Taux = T_tau_thrusters[5]
        Tau = np.array([Taux, Tauy, Tauz])

        # External forces acting on robot
        F_ext = np.zeros(3)
        F_ext = np.matmul(Q_IB(ypr),np.array([0, 0, m*g])) - np.array([Tx,Ty,Tz])

        # Project force vectors for acceleration measurements
        F_global = np.zeros(3)
        F_global = np.matmul(Q_BI(ypr),T_tau_thrusters[0:3])

        # Implement free body dynamics
        x1 = np.zeros(self.x_dim)
        xdot = np.zeros(self.x_dim)

        # global position derivative
        xdot[idx_xyz] = np.matmul(Q_BI(ypr),x0[idx_xyz_dot])

        # Euler angle derivative
        xdot[idx_ptp] = np.matmul(W_inv(ypr), x0[idx_ptp_dot])

        # body velocity derivative
        omega = x0[idx_ptp_dot]
        omega_mat = np.array([  [0, -omega[2], omega[1]],
                                [omega[2], 0, -omega[0]],
                                [-omega[1], omega[0], 0]
                                ])

        xdot[idx_xyz_dot] = (1/m)*F_ext - np.matmul(omega_mat, x0[idx_xyz_dot])

        # angular velocity derivative
        xdot[idx_ptp_dot] = np.matmul(np.linalg.inv(Ib),Tau) - np.matmul(np.matmul(np.linalg.inv(Ib),omega_mat),np.matmul(Ib,x0[idx_ptp_dot]))

        # State update
        x_noise_vec = np.random.normal(loc=0, scale = self.x_noise, size=(self.x_dim))
        x1 = x0+dt*xdot+x_noise_vec

        # Calculate accelerations
        x1[idx_xyz_ddot] = np.array([0, 0, -g]) + (F_global/m)

        # makes states less than 1e-15 = 0
        x1[np.abs(x1) < 1e-15] = 0
        return x1
