import sys, os, cv2, time, heapq, argparse
import numpy as np, math
from openvino.inference_engine import IENetwork, IEPlugin
import multiprocessing as mp
from time import sleep

m_input_size = 416

yolo_scale_13 = 13
yolo_scale_26 = 26
yolo_scale_52 = 52

classes = 80
coords = 4
num = 3
anchors = [10,13,16,30,33,23,30,61,62,45,59,119,116,90,156,198,373,326]

LABELS = ("person", "bicycle", "car", "motorbike", "aeroplane",
          "bus", "train", "truck", "boat", "traffic light",
          "fire hydrant", "stop sign", "parking meter", "bench", "bird",
          "cat", "dog", "horse", "sheep", "cow",
          "elephant", "bear", "zebra", "giraffe", "backpack",
          "umbrella", "handbag", "tie", "suitcase", "frisbee",
          "skis", "snowboard", "sports ball", "kite", "baseball bat",
          "baseball glove", "skateboard", "surfboard","tennis racket", "bottle",
          "wine glass", "cup", "fork", "knife", "spoon",
          "bowl", "banana", "apple", "sandwich", "orange",
          "broccoli", "carrot", "hot dog", "pizza", "donut",
          "cake", "chair", "sofa", "pottedplant", "bed",
          "diningtable", "toilet", "tvmonitor", "laptop", "mouse",
          "remote", "keyboard", "cell phone", "microwave", "oven",
          "toaster", "sink", "refrigerator", "book", "clock",
          "vase", "scissors", "teddy bear", "hair drier", "toothbrush")

label_text_color = (255, 255, 255)
label_background_color = (125, 175, 75)
box_color = (255, 128, 0)
box_thickness = 1

processes = []

fps = ""
detectfps = ""
framecount = 0
detectframecount = 0
time1 = 0
time2 = 0
lastresults = None

def EntryIndex(side, lcoords, lclasses, location, entry):
    n = int(location / (side * side))
    loc = location % (side * side)
    return int(n * side * side * (lcoords + lclasses + 1) + entry * side * side + loc)


class DetectionObject():
    xmin = 0
    ymin = 0
    xmax = 0
    ymax = 0
    class_id = 0
    confidence = 0.0

    def __init__(self, x, y, h, w, class_id, confidence, h_scale, w_scale):
        self.xmin = int((x - w / 2) * w_scale)
        self.ymin = int((y - h / 2) * h_scale)
        self.xmax = int(self.xmin + w * w_scale)
        self.ymax = int(self.ymin + h * h_scale)
        self.class_id = class_id
        self.confidence = confidence


def IntersectionOverUnion(box_1, box_2):
    width_of_overlap_area = min(box_1.xmax, box_2.xmax) - max(box_1.xmin, box_2.xmin)
    height_of_overlap_area = min(box_1.ymax, box_2.ymax) - max(box_1.ymin, box_2.ymin)
    area_of_overlap = 0.0
    if (width_of_overlap_area < 0.0 or height_of_overlap_area < 0.0):
        area_of_overlap = 0.0
    else:
        area_of_overlap = width_of_overlap_area * height_of_overlap_area
    box_1_area = (box_1.ymax - box_1.ymin)  * (box_1.xmax - box_1.xmin)
    box_2_area = (box_2.ymax - box_2.ymin)  * (box_2.xmax - box_2.xmin)
    area_of_union = box_1_area + box_2_area - area_of_overlap
    return (area_of_overlap / area_of_union)


def ParseYOLOV3Output(blob, resized_im_h, resized_im_w, original_im_h, original_im_w, threshold, objects):

    out_blob_h = blob.shape[2]
    out_blob_w = blob.shape[3]

    side = out_blob_h
    anchor_offset = 0

    if side == yolo_scale_13:
        anchor_offset = 2 * 6
    elif side == yolo_scale_26:
        anchor_offset = 2 * 3
    elif side == yolo_scale_52:
        anchor_offset = 2 * 0

    side_square = side * side
    output_blob = blob.flatten()

    for i in range(side_square):
        row = int(i / side)
        col = int(i % side)
        for n in range(num):
            obj_index = EntryIndex(side, coords, classes, n * side * side + i, coords)
            box_index = EntryIndex(side, coords, classes, n * side * side + i, 0)
            scale = output_blob[obj_index]
            if (scale < threshold):
                continue
            x = (col + output_blob[box_index + 0 * side_square]) / side * resized_im_w
            y = (row + output_blob[box_index + 1 * side_square]) / side * resized_im_h
            height = math.exp(output_blob[box_index + 3 * side_square]) * anchors[anchor_offset + 2 * n + 1]
            width = math.exp(output_blob[box_index + 2 * side_square]) * anchors[anchor_offset + 2 * n]
            for j in range(classes):
                class_index = EntryIndex(side, coords, classes, n * side_square + i, coords + 1 + j)
                prob = scale * output_blob[class_index]
                if prob < threshold:
                    continue
                obj = DetectionObject(x, y, height, width, j, prob, (original_im_h / resized_im_h), (original_im_w / resized_im_w))
                objects.append(obj)
    return objects


def camThread(LABELS, results, frameBuffer, camera_width, camera_height):
    global fps
    global detectfps
    global lastresults
    global framecount
    global detectframecount
    global time1
    global time2
    global cam
    global window_name

    cam = cv2.VideoCapture(0)
    if cam.isOpened() != True:
        print("USB Camera Open Error!!!")
        sys.exit(0)
    cam.set(cv2.CAP_PROP_FPS, 30)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, camera_width)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_height)
    window_name = "USB Camera"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    while True:
        t1 = time.perf_counter()

        # USB Camera Stream Read
        s, color_image = cam.read()
        if not s:
            continue
        if frameBuffer.full():
            frameBuffer.get()

        height = color_image.shape[0]
        width = color_image.shape[1]
        frameBuffer.put(color_image.copy())

        if not results.empty():
            objects = results.get(False)
            detectframecount += 1

            for obj in objects:
                if obj.confidence < 0.2:
                    continue
                label = obj.class_id
                confidence = obj.confidence
                if confidence > 0.2:
                    label_text = LABELS[label] + " (" + "{:.1f}".format(confidence * 100) + "%)"
                    cv2.rectangle(color_image, (obj.xmin, obj.ymin), (obj.xmax, obj.ymax), box_color, box_thickness)
                    cv2.putText(color_image, label_text, (obj.xmin, obj.ymin - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, label_text_color, 1)
            lastresults = objects
        else:
            if not isinstance(lastresults, type(None)):
                for obj in lastresults:
                    if obj.confidence < 0.2:
                        continue
                    label = obj.class_id
                    confidence = obj.confidence
                    if confidence > 0.2:
                        label_text = LABELS[label] + " (" + "{:.1f}".format(confidence * 100) + "%)"
                        cv2.rectangle(color_image, (obj.xmin, obj.ymin), (obj.xmax, obj.ymax), box_color, box_thickness)
                        cv2.putText(color_image, label_text, (obj.xmin, obj.ymin - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, label_text_color, 1)

        cv2.putText(color_image, fps,       (width-170,15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (38,0,255), 1, cv2.LINE_AA)
        cv2.putText(color_image, detectfps, (width-170,30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (38,0,255), 1, cv2.LINE_AA)
        cv2.imshow(window_name, cv2.resize(color_image, (width, height)))

        if cv2.waitKey(1)&0xFF == ord('q'):
            sys.exit(0)

        ## Print FPS
        framecount += 1
        if framecount >= 15:
            fps       = "(Playback) {:.1f} FPS".format(time1/15)
            detectfps = "(Detection) {:.1f} FPS".format(detectframecount/time2)
            framecount = 0
            detectframecount = 0
            time1 = 0
            time2 = 0
        t2 = time.perf_counter()
        elapsedTime = t2-t1
        time1 += 1/elapsedTime
        time2 += elapsedTime


# l = Search list
# x = Search target value
def searchlist(l, x, notfoundvalue=-1):
    if x in l:
        return l.index(x)
    else:
        return notfoundvalue


def inferencer(results, frameBuffer, device_count, camera_width, camera_height):

    plugin = None
    net = None
    inferred_request = [0] * device_count
    heap_request = []
    inferred_cnt = 0
    forced_sleep_time = (1 / device_count)

    model_xml = "./lrmodels/YoloV3/FP16/frozen_yolo_v3.xml"
    model_bin = "./lrmodels/YoloV3/FP16/frozen_yolo_v3.bin"
    plugin = IEPlugin(device="MYRIAD")
    net = IENetwork(model=model_xml, weights=model_bin)
    input_blob = next(iter(net.inputs))
    exec_net = plugin.load(network=net, num_requests=device_count)

    while True:

        try:

            if frameBuffer.empty():
                continue
            color_image = frameBuffer.get()

            prepimg = cv2.resize(color_image, (m_input_size, m_input_size))
            prepimg = prepimg[np.newaxis, :, :, :]     # Batch size axis add
            prepimg = prepimg.transpose((0, 3, 1, 2))  # NHWC to NCHW

            reqnum = searchlist(inferred_request, 0)
            if reqnum > -1:
                sleep(forced_sleep_time)
                exec_net.start_async(request_id=reqnum, inputs={input_blob: prepimg})
                inferred_request[reqnum] = 1
                inferred_cnt += 1
                if inferred_cnt == sys.maxsize:
                    inferred_request = [0] * device_count
                    heap_request = []
                    inferred_cnt = 0
                heapq.heappush(heap_request, (inferred_cnt, reqnum))

            cnt, dev = heapq.heappop(heap_request)
            if exec_net.requests[dev].wait(0) == 0:
                exec_net.requests[dev].wait(-1)

                objects = []
                outputs = exec_net.requests[dev].outputs
                for output in outputs.values():
                    objects = ParseYOLOV3Output(output, m_input_size, m_input_size, camera_height, camera_width, 0.7, objects)

                objlen = len(objects)
                for i in range(objlen):
                    if (objects[i].confidence == 0.0):
                        continue
                    for j in range(i + 1, objlen):
                        if (IntersectionOverUnion(objects[i], objects[j]) >= 0.4):
                            objects[j].confidence = 0

                results.put(objects)
                inferred_request[dev] = 0
            else:
                heapq.heappush(heap_request, (cnt, dev))

        except:
            import traceback
            traceback.print_exc()


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('-numncs','--numberofncs',dest='number_of_ncs',type=int,default=1,help='Number of NCS. (Default=1)')
    args = parser.parse_args()

    number_of_ncs = args.number_of_ncs
    camera_width = 320
    camera_height = 240

    try:

        mp.set_start_method('forkserver')
        frameBuffer = mp.Queue(10)
        results = mp.Queue()

        # Start streaming
        p = mp.Process(target=camThread, args=(LABELS, results, frameBuffer, camera_width, camera_height), daemon=True)
        p.start()
        processes.append(p)

        # Start detection MultiStick
        # Activation of inferencer
        p = mp.Process(target=inferencer, args=(results, frameBuffer, number_of_ncs, camera_width, camera_height), daemon=True)
        p.start()
        processes.append(p)

        while True:
            sleep(1)

    except:
        import traceback
        traceback.print_exc()
    finally:
        for p in range(len(processes)):
            processes[p].terminate()

        print("\n\nFinished\n\n")
