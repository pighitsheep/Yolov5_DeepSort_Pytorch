#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time : 2022/4/22 下午6:02
# @Author :zb

import os
import cv2
import torch
import warnings
import argparse
import numpy as np
import Server1
import threading
import udp
import modbus_tcp_01
import yolov5.models
# import onnxruntime as ort
from yolov5.utils.datasets import LoadStreams, LoadImages,LoadWebcam_count,LoadWebcam
from yolov5.utils.draw import draw_boxes
from yolov5.utils.general import check_img_size
from yolov5.utils.torch_utils import time_synchronized
from person_detect_yolov5 import Person_detect
from deep_sort import build_tracker
from yolov5.utils.parser import get_config
from yolov5.utils.log import get_logger
from yolov5.utils.torch_utils import select_device, load_classifier, time_synchronized
# count
from collections import Counter
from collections import deque
import math
import time
import gl_test
from PIL import Image, ImageDraw, ImageFont
from deep_sort.deep_sort import DeepSort
import warnings
warnings.filterwarnings("ignore")

def tlbr_midpoint(box):
    minX, minY, maxX, maxY = box
    midpoint = (int((minX + maxX) / 2), int((minY + maxY) / 2))  # minus y coordinates to get proper xy format
    return midpoint


def intersect(A, B, C, D):
    return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)


def ccw(A, B, C):
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])


def vector_angle(midpoint, previous_midpoint):
    x = midpoint[0] - previous_midpoint[0]
    y = midpoint[1] - previous_midpoint[1]
    return math.degrees(math.atan2(y, x))


def get_size_with_pil(label,size=25):
    font = ImageFont.truetype("./configs/simkai.ttf", size, encoding="utf-8")  # simhei.ttf
    return font.getsize(label)


#为了支持中文，用pil
def put_text_to_cv2_img_with_pil(cv2_img,label,pt,color):
    pil_img = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)  # cv2和PIL中颜色的hex码的储存顺序不同，需转RGB模式
    pilimg = Image.fromarray(pil_img)  # Image.fromarray()将数组类型转成图片格式，与np.array()相反
    draw = ImageDraw.Draw(pilimg)  # PIL图片上打印汉字
    font = ImageFont.truetype("./configs/simkai.ttf", 25, encoding="utf-8") #simhei.ttf
    draw.text(pt, label, color,font=font)
    return cv2.cvtColor(np.array(pilimg), cv2.COLOR_RGB2BGR)  # 将图片转成cv2.imshow()可以显示的数组格式


colors = np.array([
    [1,0,1],
    [0,0,1],
    [0,1,1],
    [0,1,0],
    [1,1,0],
    [1,0,0]
    ]);

def get_color(c, x, max):
    ratio = (x / max) * 5;
    i = math.floor(ratio);
    j = math.ceil(ratio);
    ratio -= i;
    r = (1 - ratio) * colors[i][c] + ratio * colors[j][c];
    return r;

def compute_color_for_labels(class_id,class_total=80):
    offset = (class_id + 0) * 123457 % class_total;
    red = get_color(2, offset, class_total);
    green = get_color(1, offset, class_total);
    blue = get_color(0, offset, class_total);
    return (int(red*256),int(green*256),int(blue*256))




class yolo_reid():
    def __init__(self, cfg, args, path):

        self.logger = get_logger("root")
        self.args = args
        self.video_path = path

        use_cuda = args.use_cuda and torch.cuda.is_available()
        if not use_cuda:
            warnings.warn("Running in cpu mode which maybe very slow!", UserWarning)

        self.person_detect = Person_detect(self.args, self.video_path)
        imgsz = check_img_size(args.img_size, s=32)  # self.model.stride.max())  # check img_size
        # print('ssssssssssssssssssssssssssssssssssssssssssss%s'%imgsz)
        self.dataset = LoadImages(self.video_path, img_size=imgsz)
        #考虑使用视频还是webcam
        #webcam pipe==0 （目前还在videopath直接为0） 视频为路径''
        # self.dataset = LoadWebcam_count(self.video_path, img_size=imgsz)

        # self.dataset = LoadWebcam(self.video_path, img_size=imgsz)
        self.deepsort = build_tracker(cfg,  use_cuda=use_cuda)#args.sort,


    def deep_sort(self):
        #socket tcp/ip
        # tt1 = threading.Thread(target=Server1.socp)
        # tt1.start()
        #modbus tcp
        tt2 = threading.Thread(target=modbus_tcp_01.catch)
        tt2.start()
        #socket udp
        # tt3 = threading.Thread(target=udp.catch)
        # tt3.start()
        #time out
        # tt4 = threading.Thread(target=gl_test.data_clear)
        # tt4.start()
        text_gl=[]
        que_mb = deque()

        idx_frame = 0
        results = []
        paths = {}
        track_cls = 0
        last_track_id = -1
        total_track = 0
        angle = -1
        total_counter = 0
        up_count = 0
        down_count = 0
        X = np.array([[0.133322, -0.708023], [-0.685687, -0.133332]])
        class_counter = Counter()   # store counts of each detected class
        already_counted = deque(maxlen=50)   # temporary memory for storing counted IDs

        for video_path, img, ori_img, vid_cap in self.dataset:
            # print(video_path,img,ori_img,vid_cap)
            # test_img = ori_img
            idx_frame += 1
            # print('aaaaaaaa', video_path, img.shape, im0s.shape, vid_cap)
            t1 = time_synchronized()

            # yolo detection
            bbox_xywh, cls_conf, cls_ids, xy = self.person_detect.detect(video_path, img, ori_img, vid_cap)

            # do tracking
            outputs = self.deepsort.update(bbox_xywh, cls_conf,  cls_ids,ori_img)
            # print(outputs)

            # 1.视频中间画行黄线，
            # line = [(0, int(0.8 * ori_img.shape[0])), (int(ori_img.shape[1]), int(0.8 * ori_img.shape[0]))]
            line = [(int(0.5*ori_img.shape[1]), 0), (int(0.5*ori_img.shape[1]), int(1* ori_img.shape[0]))]
            #（原图，pt1，pt2，color，线宽）
            cv2.line(ori_img, line[0], line[1], (0, 255, 255), 5)
            #清空列表
            # gl_test.GLOBAL_TEST.clear()

            # 2. 统计人数
            for track in outputs:
                bbox = track[:4]
                track_id = track[4]
                #中心点
                global tlbr_midpoint
                midpoint = tlbr_midpoint(bbox)
                origin_midpoint = (midpoint[0], ori_img.shape[0] - midpoint[1])  # get midpoint respective to botton-left
                bbbox= track[:5]

                if track_id not in paths:
                    paths[track_id] = deque(maxlen=2)
                    total_track = track_id
                paths[track_id].append(midpoint)
                previous_midpoint = paths[track_id][0]#应该为前一个中心点
                #前一个中心点距离左下角距离
                origin_previous_midpoint = (previous_midpoint[0], ori_img.shape[0] - previous_midpoint[1])

                if intersect(midpoint, previous_midpoint, line[0], line[1]) and track_id not in already_counted:
                    class_counter[track_cls] += 1
                    total_counter += 1
                    last_track_id = track_id;
                    # draw red line
                    cv2.line(ori_img, line[0], line[1], (0, 0, 255), 10)

                    already_counted.append(track_id)  # Set already counted for ID to true.
                    #新中心点到左下角减去前一帧中心点到左下角距离的正切值转为角度
                    angle = vector_angle(origin_midpoint, origin_previous_midpoint)
                    #参数转发
                    #wide height
                    bbbox_x=bbbox[2]-bbbox[0]
                    bbbox_y=bbbox[3]-bbbox[1]
                    #范围————————后面考虑像素面积
                    bbbox_dl=0
                    #上下范围位置————
                    if int(bbbox_y) >=bbbox_dl or int(bbbox_x)>=bbbox_dl:
                        #仿射变换
                        midpoint_list=list(midpoint)
                        if 800< midpoint_list[1] <1550:
                            a1 = np.array(midpoint_list)
                            b1 = np.dot(X, a1) + [1259.88, 2008.76]
                            t=time.time()
                            midpoint_tuple=tuple(b1)+(t,)
                            que_mb.append(midpoint_tuple)
                            gl_test.GLOBAL_TEST=que_mb

                            # text_gl.insert(0,midpoint_tuple)#先进后出
                            # print(midpoint_tuple)
                            # gl_test.GLOBAL_TEST=text_gl

                        if angle > 0:
                            up_count += 1
                        if angle < 0:
                            down_count += 1

            if len(paths) > 50:
                del paths[list(paths)[0]]

            # 3. 绘制人员
            if len(outputs) > 0:
                bbox_tlwh = []
                bbox_xyxy = outputs[:, :4]
                identities = outputs[:,4]
                # print(identities)
                ori_img = draw_boxes(ori_img, bbox_xyxy, identities)
                for bb_xyxy in bbox_xyxy:
                    bbox_tlwh.append(self.deepsort._xyxy_to_tlwh(bb_xyxy))
                # results.append((idx_frame - 1, bbox_tlwh, identities))
            # print("yolo+deepsort:", time_synchronized() - t1)

            # 4. 绘制统计信息
            label = "矸石总数: {}".format(str(total_track))
            t_size = get_size_with_pil(label, 25)
            x1 = 20
            y1 = 50
            color = compute_color_for_labels(2)
            cv2.rectangle(ori_img, (x1 - 1, y1), (x1 + t_size[0] + 10, y1 - t_size[1]), color, 2)
            ori_img = put_text_to_cv2_img_with_pil(ori_img, label, (x1 + 5, y1 - t_size[1] - 2), (0, 0, 0))
            label = "穿过黄线矸石: {} ({} 向上, {} 向下)".format(str(total_counter), str(up_count), str(down_count))
            t_size = get_size_with_pil(label, 25)
            x1 = 20
            y1 = 100
            color = compute_color_for_labels(2)
            cv2.rectangle(ori_img, (x1 - 1, y1), (x1 + t_size[0] + 10, y1 - t_size[1]), color, 2)
            ori_img = put_text_to_cv2_img_with_pil(ori_img, label, (x1 + 5, y1 - t_size[1] - 2), (0, 0, 0))

            if last_track_id >= 0:
                label = "最新: 矸石{}号{}穿过黄线".format(str(last_track_id), str("向上") if angle >= 0 else str('向下'))
                t_size = get_size_with_pil(label, 25)
                x1 = 20
                y1 = 150
                color = compute_color_for_labels(2)
                cv2.rectangle(ori_img, (x1 - 1, y1), (x1 + t_size[0] + 10, y1 - t_size[1]), color, 2)
                ori_img = put_text_to_cv2_img_with_pil(ori_img, label, (x1 + 5, y1 - t_size[1] - 2), (255, 0, 0))

            end = time_synchronized()
            # self.__init__()
            # self.cv2.get()
            if self.args.display:
                cv2.imshow("test", ori_img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            # self.logger.info("{}/time: {:.03f}s, fps: {:.03f}, detection numbers: {}, tracking numbers: {}" \
            #                  .format(idx_frame, end - t1, 1 / (end - t1),
            #                          bbox_xywh.shape[0], len(outputs)))



def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video_path", default="MOT Challenge.mp4", type=str)
    parser.add_argument("--camera", action="store", dest="cam", type=int, default="-1")
    parser.add_argument('--device', default='cuda:0', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    # yolov5
    parser.add_argument('--weights', nargs='+', type=str, default=r'E:\yolov5-6.1\runs\train\exp5\weights\best.pt', help='model.pt path(s)')
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--conf-thres', type=float, default=0.4, help='object confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.5, help='IOU threshold for NMS')
    parser.add_argument('--classes', default=[0], type=int, help='filter by class: --class 0, or --class 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    # deep_sort
    parser.add_argument("--sort", default=True, help='True: sort model, False: reid model')
    parser.add_argument("--config_deepsort", type=str, default="deep_sort/configs/deep_sort.yaml")
    parser.add_argument("--display", default=True, help='show result')
    parser.add_argument("--frame_interval", type=int, default=0)
    parser.add_argument("--cpu", dest="use_cuda", action="store_false", default=True)
    return parser.parse_args()



if __name__ == '__main__':
    args = parse_args()
    cfg = get_config()
    cfg.merge_from_file(args.config_deepsort)

    yolo_reid = yolo_reid(cfg, args, path=args.video_path)
    with torch.no_grad():
        yolo_reid.deep_sort()