#!/usr/bin/env python2

# Copyright (c) 2021 Ruichao Wu

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import actionlib
import copy
import math
import rospy
import numpy as np

from control_msgs.msg import FollowJointTrajectoryAction
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


def trajectory_is_finite(trajectory):
    """Check if trajectory contains infinite or NaN value."""
    for point in trajectory.points:
        for position in point.positions:
            if math.isinf(position) or math.isnan(position):
                return False
        for velocity in point.velocities:
            if math.isinf(velocity) or math.isnan(velocity):
                return False
    return True


def has_velocities(trajectory):
    """Check that velocities are defined for this trajectory."""
    for point in trajectory.points:
        if len(point.velocities) != len(point.positions):
            return False
    return True


def reorder_trajectory_joints(trajectory, joint_names):
    """Reorder the trajectory points according to the order in joint_names."""
    order = [trajectory.joint_names.index(j) for j in joint_names]
    new_points = []
    for point in trajectory.points:
        new_points.append(JointTrajectoryPoint(
            positions=[point.positions[i] for i in order],
            velocities=[point.velocities[i] for i in order] if point.velocities else [],
            accelerations=[point.accelerations[i] for i in order] if point.accelerations else [],
            time_from_start=point.time_from_start))
    trajectory.joint_names = joint_names
    trajectory.points = new_points


def within_tolerance(a_vec, b_vec, tol_vec):
    """Check if two vectors are equals with a given tolerance."""
    for a, b, tol in zip(a_vec, b_vec, tol_vec):
        if abs(a - b) > tol:
            return False
    return True


def from_distance_to_radians(self, linear_pose):
    """
    Private helper function to convert a command in meters to radians (joint value)
    """
    self._max_joint_limit = 0.8
    self._stroke = 0.085
    return np.clip(self._max_joint_limit - ((self._max_joint_limit / self._stroke) * linear_pose), 0.0,
                   self._max_joint_limit)


def from_radians_to_distance(joint_pose):
    """
    Private helper function to convert a joint position in radians to meters (distance between fingers)
    """
    _max_joint_limit = 0.8
    _stroke = 0.085
    ## return position
    return np.clip(_stroke - ((_stroke / _max_joint_limit) * joint_pose), 0.0, _max_joint_limit)


def interp_cubic(p0, t_abs):
    """Perform a cubic interpolation between two trajectory points."""

    q = [0] * 1
    qdot = [0] * 1
    qddot = [0] * 1
    """  
       T = (p1.time_from_start - p0.time_from_start).to_sec()
    t = t_abs - p0.time_from_start.to_sec()
    q = [0] * joint_num
    qdot = [0] * joint_num
    qddot = [0] * joint_num   
    """
    for i in range(len(p0.positions)):
        # print i
        target_speed = p0.velocities[i] if len(p0.velocities) > 0 else 0.01
        q[i] = from_radians_to_distance(p0.positions[i])
        qdot[i] = abs(target_speed)
        qddot[i] = 0

    return JointTrajectoryPoint(positions=q, velocities=qdot, accelerations=qddot,
                                time_from_start=rospy.Duration(t_abs))


def sample_trajectory(trajectory, t):
    """Return (q, qdot, qddot) for sampling the JointTrajectory at time t,
       the time t is the time since the trajectory was started."""
    # first
    if t <= 0.0:
        # print "first: {}".format(t)
        #print trajectory.points[0].positions
        return copy.deepcopy(trajectory.points[0])
    # Last point
    if t >= trajectory.points[-1].time_from_start.to_sec():
        #print "last: {}".format(t)
        #print trajectory.points[-1].positions
        return copy.deepcopy(trajectory.points[-1])
    # Finds the (middle) segment containing

    i = 0
    while trajectory.points[i + 1].time_from_start.to_sec() < t:
        i += 1
    #print "trajectory.points {}: {}".format(i, trajectory.points[i].positions)
    return interp_cubic(trajectory.points[i], t)


class TrajectoryFollowerGripper(object):
    """Create and handle the action 'follow_joint_trajectory' server."""

    jointNames = [
        'gripper_finger1_joint'
    ]
    
    internjointNames = [
        'gripper_finger1_joint',
        'gripper_finger2_joint'
    ]

    def __init__(self, robot, jointStatePublisher, jointPrefix, goal_time_tolerance=None):
        self.robot = robot
        self.jointPrefix = jointPrefix
        self.prefixedJointNames = [s + self.jointPrefix for s in TrajectoryFollowerGripper.jointNames]
        print(self.prefixedJointNames)
        self.jointStatePublisher = jointStatePublisher
        self.timestep = int(robot.getBasicTimeStep())
        self.motors = []
        self.sensors = []
        for name in TrajectoryFollowerGripper.internjointNames:
            self.motors.append(robot.getDevice(name))
            self.sensors.append(robot.getDevice(name + '_sensor'))
            self.sensors[-1].enable(self.timestep)
            print('init motor: {}'.format(self.motors))
        
        self.goal_handle = None
        self.last_point_sent = True
        self.trajectory = None
        self.joint_goal_tolerances = [0.05]
        self._max_joint_limit = 0.8
        self._stroke = 0.085

        self.server = actionlib.ActionServer("gripper_controller/follow_joint_trajectory",
                                             FollowJointTrajectoryAction,
                                             self.on_goal, self.on_cancel, auto_start=False)

    def init_trajectory(self):
        """Initialize a new target trajectory."""
        state = self.jointStatePublisher.last_joint_states
        self.trajectory_t0 = self.robot.getTime()
        
        # gripper_finger1_joint
        self.trajectory = JointTrajectory()
        self.trajectory.joint_names = self.prefixedJointNames
        print 'init trajectory.joint_names:{}'.format(self.trajectory.joint_names)
        
        self.trajectory.points = [JointTrajectoryPoint(
            positions=state.position if state else [0] * 1,
            velocities=[0] * 1,
            accelerations=[0] * 1,
            time_from_start=rospy.Duration(0.0))]

    def start(self):
        """Initialize and start the action server."""
        self.init_trajectory()
        self.server.start()
        print("The action server for gripper has been started")

    def on_goal(self, goal_handle):
        """Handle a new goal trajectory command."""
        # Checks if the joints are just incorrect
        if set(goal_handle.get_goal().trajectory.joint_names) != set(self.prefixedJointNames):
            rospy.logerr("Received a goal with incorrect joint names: (%s)" %
                         ', '.join(goal_handle.get_goal().trajectory.joint_names))
            goal_handle.set_rejected()
            return

        if not trajectory_is_finite(goal_handle.get_goal().trajectory):
            rospy.logerr("Received a goal with infinites or NaNs")
            goal_handle.set_rejected(text="Received a goal with infinites or NaNs")
            return

        # Checks that the trajectory has velocities
        if not has_velocities(goal_handle.get_goal().trajectory):
            rospy.logerr("Received a goal without velocities")
            goal_handle.set_rejected(text="Received a goal without velocities")
            return

        print("on goal: {}".format(goal_handle.get_goal().trajectory))
        rospy.loginfo("gripper on goal")
        # Orders the joints of the trajectory according to joint_names
        reorder_trajectory_joints(goal_handle.get_goal().trajectory, self.prefixedJointNames)
        # Inserts the current setpoint at the head of the trajectory
        now = self.robot.getTime()
        #print 'trajectory_t0: {}'.format(self.trajectory_t0)
        point0 = sample_trajectory(self.trajectory, now - self.trajectory_t0)

        point0.time_from_start = rospy.Duration(0.0)
        goal_handle.get_goal().trajectory.points.insert(0, point0)
        self.trajectory_t0 = now
        #print "i am here"
        #print 'point0: {}'.format(point0.positions)
        # Replaces the goal
        self.goal_handle = goal_handle
        self.trajectory = goal_handle.get_goal().trajectory
        goal_handle.set_accepted()

    def on_cancel(self, goal_handle):
        """Handle a trajectory cancel command."""
        if goal_handle == self.goal_handle:
            # stop the motors
            for i in range(len(TrajectoryFollowerGripper.internjointNames)):
                self.motors[i].setPosition(self.sensors[i].getValue())
            self.goal_handle.set_canceled()
            self.goal_handle = None
        else:
            goal_handle.set_canceled()

    def update(self):
        if self.robot and self.trajectory:
            now = self.robot.getTime()
            if (now - self.trajectory_t0) <= self.trajectory.points[-1].time_from_start.to_sec():  # Sending intermediate points
                self.last_point_sent = False
                setpoint = sample_trajectory(self.trajectory, now - self.trajectory_t0)
                for i in range(len(setpoint.positions)):
                    self.motors[i].setPosition(setpoint.positions[i])
                    self.motors[1].setPosition(setpoint.positions[i])
                # print 'update motors i: {}'.format(i)
                    # Velocity control is not used on the real robot and gives bad results in the simulation
                    # self.motors[i].setVelocity(math.fabs(setpoint.velocities[i]))
            elif not self.last_point_sent:  # All intermediate points sent, sending last point to make sure we reach the goal.
                last_point = self.trajectory.points[-1]
                state = self.jointStatePublisher.last_joint_states
                position_in_tol = within_tolerance(state.position, last_point.positions, self.joint_goal_tolerances)
                setpoint = sample_trajectory(self.trajectory, self.trajectory.points[-1].time_from_start.to_sec())
                for i in range(len(setpoint.positions)):
                    self.motors[i].setPosition(setpoint.positions[i])
                    self.motors[1].setPosition(setpoint.positions[i])
                self.last_point_sent = True
                #print 'last point gripper'
                if self.goal_handle:
                    #print 'gripper successed'
                    self.goal_handle.set_succeeded()
                    self.goal_handle = None
                    state = self.jointStatePublisher.last_joint_states
                    position_in_tol = within_tolerance(state.position, last_point.positions, [0.1] * 1)
                    velocity_in_tol = within_tolerance(state.velocity, last_point.velocities, [0.05] * 1)
                    #print 'gripper finish'
                    # Velocity control is not used on the real robot and gives bad results in the simulation
                    # self.motors[i].setVelocity(math.fabs(setpoint.velocities[i]))
            else:  # Off the end
                if self.goal_handle:
                    last_point = self.traj.points[-1]
                    state = self.jointStatePublisher.last_joint_states
                    position_in_tol = within_tolerance(state.position, last_point.positions, [0.1] * 1)
                    velocity_in_tol = within_tolerance(state.velocity, last_point.velocities, [0.05] * 1)
                    if position_in_tol and velocity_in_tol:
                        # The arm reached the goal (and isn't moving) => Succeeded
                        self.goal_handle.set_succeeded()
                        self.goal_handle = None