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

"""Joint state publisher with gripper joint."""

import rospy
from sensor_msgs.msg import JointState


class JointStatePublisher(object):
    """Publish as a ROS topic the joint state."""

    jointNames = [
        'shoulder_pan_joint',
        'shoulder_lift_joint',
        'elbow_joint',
        'wrist_1_joint',
        'wrist_2_joint',
        'wrist_3_joint',
        'gripper_finger1_joint'
        ]

    def __init__(self, robot, jointPrefix, nodeName):
        """Initialize the motors, position sensors and the topic."""
        self.robot = robot
        self.jointPrefix = jointPrefix
        self.motors = []
        self.sensors = []
        self.timestep = int(robot.getBasicTimeStep())
        self.last_joint_states = None
        self.previousTime = 0
        self.previousPosition = []
        for name in JointStatePublisher.jointNames:
            self.motors.append(robot.getDevice(name))
            self.sensors.append(robot.getDevice(name + '_sensor'))
            self.sensors[-1].enable(self.timestep)
            self.previousPosition.append(0)
        self.publisher = rospy.Publisher(nodeName + 'joint_states', JointState, queue_size=1)

    def publish(self):
        """Publish the 'joint_states' topic with up to date value."""
        msg = JointState()
        msg.header.stamp = rospy.get_rostime()
        msg.header.frame_id = "From simulation state data"
        msg.name = [s + self.jointPrefix for s in JointStatePublisher.jointNames]
        msg.position = []
        timeDifference = self.robot.getTime() - self.previousTime
        for i in range(len(self.sensors)):
            value = self.sensors[i].getValue()
            msg.position.append(value)
            msg.velocity.append((value - self.previousPosition[i]) / timeDifference if timeDifference > 0 else 0.0)
            self.previousPosition[i] = value
        msg.effort = [0] * 7
        self.publisher.publish(msg)
        self.last_joint_states = msg
        self.previousTime = self.robot.getTime()