#!/usr/bin/env python
import rospy
import cv2
import numpy as np
from std_msgs.msg import Int32, Int32MultiArray, Float32, Bool
from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import Image
import time
from Tkinter import Button, Tk


LANE_DETECTION_NODE_NAME = 'side_lane_detection_node'
CAMERA_TOPIC_NAME = '/zed2/zed_node/rgb/image_rect_color'
CENTROID_TOPIC_NAME = '/centroid'
OTHER_CAR_TOPIC_NAME = '/racecar_position'

global mid_x, mid_y
mid_x = Int32()
mid_y = Int32()


def decodeImage(data, height, width):
    decoded = np.fromstring(data, dtype=np.uint8)
    decoded = decoded.reshape((height, width, 4))
    return decoded[:, :, :3]


class LaneDetection:
    def __init__(self):
        # Initialize node and create publishers/subscribers
        self.init_node = rospy.init_node(LANE_DETECTION_NODE_NAME, anonymous=False)
        self.camera_subscriber = rospy.Subscriber(CAMERA_TOPIC_NAME, Image, self.locate_centroid)
        self.centroid_error_publisher = rospy.Publisher(CENTROID_TOPIC_NAME, Float32, queue_size=1)
        self.other_vehicle_pose_subscriber = rospy.Subscriber(OTHER_CAR_TOPIC_NAME,PointStamped, self.overtake_decision)
        self.Hue_low = 32 # 32
        self.Hue_high = 53 # 53
        self.Saturation_low = 70
        self.Saturation_high = 255
        self.Value_low = 0
        self.Value_high = 255
        # ^Above values are tuned for yellow tape detection in indoor environment (Levine Hall)
        self.inverted_filter = 0
        self.number_of_lines = 5
        self.error_threshold = 0.1
        self.min_width = 0
        self.max_width = 671
        # original width: 672
        # original height: 376
        self.start_height = 90
        self.bottom_height = 375
        self.left_width = 0
        self.right_width = 671

        self.lane_Hue_low = 20
        self.lane_Hue_high = 240
        self.lane_Saturation_low = 0
        self.lane_Saturation_high = 255 
        self.lane_Value_low = 190
        self.lane_Value_high = 255
        #For white tape detection(lane outer markings)

        self.left=True      #Following left lane = True, Following right lane = False
        self.overtake_threshold = 2     # Longitudinal overtake threshold 
        self.overtake_time = 0.0        # Keeps track of when overtaking is performed
        self.overtake_time_threshold = 2.33/1.2     # Distance/Speed (Assuming static obstacle)
        self.swap_back = True

        def left_callback():
            self.left=True

        def right_callback():
            self.left=False

        self.master=Tk()
        self.l = Button(self.master, text="LEFT", command=left_callback)  
        self.r = Button(self.master, text="RIGHT", command=right_callback)  
        self.l.pack()
        self.r.pack()
        self.master.mainloop()

        # Display Parameters
        rospy.loginfo(
            '\nHue_low: {}'.format(self.Hue_low) +
            '\nHue_high: {}'.format(self.Hue_high) +
            '\nSaturation_low: {}'.format(self.Saturation_low) +
            '\nSaturation_high: {}'.format(self.Saturation_high) +
            '\nValue_low: {}'.format(self.Value_low) +
            '\nValue_high: {}'.format(self.Value_high) +
            '\ninverted_filter: {}'.format(self.inverted_filter) +
            '\nnumber_of_lines: {}'.format(self.number_of_lines) +
            '\nerror_threshold: {}'.format(self.error_threshold) +
            '\nmin_width: {}'.format(self.min_width) +
            '\nmax_width: {}'.format(self.max_width) +
            '\nstart_height: {}'.format(self.start_height) +
            '\nbottom_height: {}'.format(self.bottom_height) +
            '\nleft_width: {}'.format(self.left_width) +
            '\nright_width: {}'.format(self.right_width))

    def overtake_decision(self, data):
        other_x=data.point.x
        other_y=data.point.y
        other_rel_speed = data.point.z
        current_time=rospy.get_time()
        if (other_y < self.overtake_threshold       # Obstacle within longitudinal threshold
            and (other_x < 0.485 and other_x > -0.235)      # Obstacle within lateral threshold
            and current_time > self.overtake_time + 10):        # Cooldown period after overtake maneuver 
            #and current_time > self.overtake_time + self.overtake_time_threshold):
            print("Lane Changed")
            self.left=not self.left     # Change Lanes
            self.overtake_time=rospy.get_time()     #Time of overtake decision
            self.swap_back = False      # 
            #self.overtake_threshold=-(self.overtake_threshold+0.33)/other_rel_speed      #Time to overtake


    def locate_centroid(self, data):
        # Image processing from rosparams
        frame = decodeImage(data.data, 376, 672)
        #cv2.imshow('frame', frame)

        # cropping
        self.image_width = int(self.right_width - self.left_width)
        img = frame[self.start_height:self.bottom_height, self.left_width:self.right_width]
        #left_tri = np.array([(0, 0), (0, img.shape[0]-1), (int(img.shape[1] * 0.25), 0)])
        #right_tri = np.array([(img.shape[1]-1, 0), (img.shape[1]-1, img.shape[0]-1), (int(img.shape[1] * 0.75), 0)])
        #img = cv2.drawContours(img, [left_tri, right_tri], -1, (255,255,255), -1)

        img = cv2.GaussianBlur(img, (3,3), cv2.BORDER_DEFAULT)
        #kernel_3 = np.ones((3,3), np.uint8)
        kernel_5 = np.ones((5,5), np.uint8)
        #img = cv2.erode(img, kernel_3, iterations=1)
        img = cv2.dilate(img, kernel_5, iterations=1)

        #cv2.imshow('cropped', img)

        image_width = self.right_width-self.left_width

        # changing color space to HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # setting threshold limits for white color filter
        lower = np.array([self.Hue_low, self.Saturation_low, self.Value_low])
        upper = np.array([self.Hue_high, self.Saturation_high, self.Value_high])
        mask = cv2.inRange(hsv, lower, upper)

        lane_lower = np.array([self.lane_Hue_low, self.lane_Saturation_low, self.lane_Value_low])
        lane_upper = np.array([self.lane_Hue_high, self.lane_Saturation_high, self.lane_Value_high])
        lane_mask = cv2.inRange(hsv, lane_lower, lane_upper)

        # creating true/false image
        if self.inverted_filter == 1:
            bitwise_mask = cv2.bitwise_and(img, img, mask=cv2.bitwise_not(mask))
        else:
            bitwise_mask = cv2.bitwise_and(img, img, mask=mask)

        lane_bitwise_mask= cv2.bitwise_and(img,img, mask=lane_mask)
        lane_gray = cv2.cvtColor(lane_bitwise_mask, cv2.COLOR_BGR2GRAY)

        # changing to gray color space
        gray = cv2.cvtColor(bitwise_mask, cv2.COLOR_BGR2GRAY)

        # changing to black and white color space
        gray_lower = 25
        gray_upper = 255
        (dummy, blackAndWhiteImage) = cv2.threshold(gray, gray_lower, gray_upper, cv2.THRESH_BINARY)
        contours, dummy = cv2.findContours(blackAndWhiteImage, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE) # CHAIN_APPROX_NONE

        (dummy, lane_blackAndWhiteImage) = cv2.threshold(lane_gray, gray_lower, gray_upper, cv2.THRESH_BINARY)
        lane_contours, dummy = cv2.findContours(lane_blackAndWhiteImage, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

        sort_cnt = sorted(lane_contours, key=cv2.contourArea)
        try:
            c=sort_cnt[-2]
            x,y,w,h = cv2.boundingRect(c)
            #img = cv2.drawContours(img, c, -1, (0, 255, 0), 3)
            cm = cv2.moments(c)
            cmx = int(cm['m10'] / cm['m00'])
            cmy = int(cm['m01'] / cm['m00'])
        except:
            print("Unable to see other lane")
        try:
            d=sort_cnt[-1]
            x,y,w,h = cv2.boundingRect(d)
            #img = cv2.drawContours(img, d, -1, (0, 255, 0), 3)
            dm = cv2.moments(d)
            dmx = int(dm['m10'] / dm['m00'])
            dmy = int(dm['m01'] / dm['m00'])
        except:
            print("Can't see lane")
        # Setting up data arrays
        centers = []
        cx_list = []
        cy_list = []

        # Defining points of a line to be drawn for visualizing error
        start_point = (int(self.image_width/2),0)
        end_point = (int(self.image_width/2),int(self.bottom_height))

        # plotting contours and their centroids
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if self.min_width < w < self.max_width:
                try:
                    x, y, w, h = cv2.boundingRect(contour)
                    # img = cv2.drawContours(img.astype(np.float32), contour, -1, (0, 255, 0), 3)
                    img = cv2.drawContours(img, contour, -1, (0, 255, 0), 3)
                    m = cv2.moments(contour)
                    cx = int(m['m10'] / m['m00'])
                    cy = int(m['m01'] / m['m00'])
                    centers.append([cx, cy])
                    cx_list.append(cx)
                    cy_list.append(cy)
                    cv2.circle(img, (cx, cy), 7, (255, 0, 0), -1)
                    img = cv2.line(img, start_point, end_point, (0,0,0), 2)
                    #img = cv2.line(img, start_point_thresh_pos, end_point_thresh_pos, (0,0,255), 2)
                    #img = cv2.line(img, start_point_thresh_neg, end_point_thresh_neg, (0,0,255), 2)
                except ZeroDivisionError:
                    pass

        # Further image processing to determine optimal steering value
        try:
            if len(cx_list) >= 1:
                error_list = []
                count = 0
                for cx_pos in cx_list:
                    #error = float((float(self.image_width/2) - cx_pos) / (self.image_width/2))
                    error = float((float(self.image_width/2) - (cx_pos+float(self.image_width)/4)) / (self.image_width/2)) # TEST FOR LANE
                    error_list.append(error)

                for error in error_list:
                    if abs(error) < self.error_threshold:
                        error = 0
                        error_list[count] = error
                    count += 1
                try:
                    cy_index=cy_list.index(sorted(cy_list)[1])
                except:
                    cy_index=1
                    print("Not enough points")
                try:
                    mid_x=cx_list[cy_index]+self.image_width/6.5#(self.image_width)*side_change
                    mid_x2=cx_list[cy_index]-self.image_width/6.5#(self.image_width)*side_change
                except:
                    mid_x=self.image_width/2
                    mid_x2=self.image_width/2
                err1 = mid_x-self.image_width/2     #right lane
                err2 = mid_x2-self.image_width/2    #left lane
                if(abs(err1)<abs(err2)):
                    print("right lane")
                else:
                    print("left lane")    
                #cv2.circle(img, (mid_x, cmy), 7, (0, 0, 255), -1)
                draw_y=65
                cv2.circle(img, (int(mid_x), draw_y), 7, (0, 50, 200), -1)
                start_point_error = (int(image_width/2), mid_y)
                #img = cv2.line(img, start_point_error, (mid_x, mid_y), (0,0,255), 4)

                #cv2.circle(img, (mid_x2, dmy), 7, (0, 0, 255), -1)
                cv2.circle(img, (int(mid_x2), draw_y), 7, (0, 0, 255), -1)
                #img = cv2.line(img, start_point_error, (mid_x2, mid_y), (0,0,255), 4)
                self.centroid_error = Float32()
                if(rospy.get_time()>self.overtake_time+2.5 and self.swap_back==False):      #Swap back lanes after overtaking
                    self.swap_back=True
                    self.left = not self.left
                if(self.left):
                    error_x=-err2/985
                    print("following left")
                else:
                    error_x=-err1/985
                    print("following right")
                self.centroid_error.data = float(error_x)
                self.centroid_error_publisher.publish(self.centroid_error)
                print("Publish err: {}".format(error_x))
                centers = []
                cx_list = []
                cy_list = []
        
            centers = []
            cx_list = []
            cy_list = []
            error_list = [0] * self.number_of_lines
        except ValueError:
            pass

        # plotting results
        #cv2.imshow('lane_blackAndWhiteImage', lane_blackAndWhiteImage)
        #cv2.imshow('img', img)
        #cv2.imshow('blackAndWhiteImage', blackAndWhiteImage)
        
        cv2.waitKey(1)
        #print(mid_x, mid_y)


def main():
    lane_detector = LaneDetection()
    rate = rospy.Rate(20)
    while not rospy.is_shutdown():
        rospy.spin()
        rate.sleep()

if __name__ == '__main__':
    main()
