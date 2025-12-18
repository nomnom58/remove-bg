from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import Response
import io, json, time
from PIL import Image
import numpy as np
import cv2
from rembg import remove

app = FastAPI()

def log_step(start, label):
    print(f"[{label}] {(time.time()-start)*1000:.1f} ms")

DEFAULT_OPTIONS = {
    "shadow": {"enabled": True, "intensity": 0.6, "blur": 35, "offset": {"x": 40, "y": 60}},
    "background": "transparent",
    "max_size": 1600
}

def merge_options(user_opts):
    o = json.loads(json.dumps(DEFAULT_OPTIONS))
    if not user_opts: return o
    if "shadow" in user_opts: o["shadow"].update(user_opts["shadow"])
    if "background" in user_opts: o["background"] = user_opts["background"]
    if "max_size" in user_opts: o["max_size"] = int(user_opts["max_size"])
    return o

def load_and_preprocess_image(file_bytes, max_size):
    start = time.time()
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    w,h = img.size
    if max(w,h)>max_size:
        s = max_size/max(w,h)
        img = img.resize((int(w*s), int(h*s)), Image.BILINEAR)
    log_step(start,"load")
    return img

def preprocess_for_segmentation(pil_img):
    arr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(arr, cv2.COLOR_BGR2LAB)
    l,a,b=cv2.split(lab)
    clahe=cv2.createCLAHE(2.0,(8,8))
    l=clahe.apply(l)
    lab=cv2.merge((l,a,b))
    arr=cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    gray=cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    if gray.mean()<110:
        gamma=1.3
        inv=1/gamma
        table=(np.arange(256)/255.0)**inv*255
        arr=cv2.LUT(arr, table.astype("uint8"))
    arr=cv2.fastNlMeansDenoisingColored(arr,None,3,3,7,21)
    blur=cv2.GaussianBlur(arr,(0,0),1)
    arr=cv2.addWeighted(arr,1.5,blur,-0.5,0)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))

def get_refined_mask(pil_img):
    buf=io.BytesIO()
    pil_img.save(buf,format="PNG")
    mask_bytes=remove(buf.getvalue(),only_mask=True)
    m=Image.open(io.BytesIO(mask_bytes)).convert("L")
    m=np.array(m)
    _,b=cv2.threshold(m,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    k=np.ones((3,3),np.uint8)
    op=cv2.morphologyEx(b,cv2.MORPH_OPEN,k,1)
    cl=cv2.morphologyEx(op,cv2.MORPH_CLOSE,k,1)
    shrink=cv2.erode(cl,k,1)
    expand=cv2.dilate(cl,k,1)
    ref=(0.6*expand+0.4*shrink).astype(np.uint8)
    fe=cv2.GaussianBlur(ref,(5,5),0)
    return fe

def compose_foreground(orig, mask, background, canvas_size):
    w,h=orig.size
    mask=cv2.resize(mask,(w,h))
    ys,xs=np.where(mask>10)
    if len(xs)==0:
        if background=="white":
            return Image.new("RGB",(canvas_size,canvas_size),(255,255,255)),None
        else:
            return Image.new("RGBA",(canvas_size,canvas_size),(0,0,0,0)),None

    minx,maxx=xs.min(),xs.max()
    miny,maxy=ys.min(),ys.max()
    obj=orig.crop((minx,miny,maxx+1,maxy+1))
    obj_mask=mask[miny:maxy+1, minx:maxx+1]
    ow,oh=obj.size
    target_h=int(canvas_size*0.75)
    s=target_h/oh
    nw,nh=int(ow*s),int(oh*s)
    obj=obj.resize((nw,nh))
    obj_mask=cv2.resize(obj_mask,(nw,nh))

    if background=="white":
        canvas=Image.new("RGB",(canvas_size,canvas_size),(255,255,255))
    else:
        canvas=Image.new("RGBA",(canvas_size,canvas_size),(0,0,0,0))

    x=(canvas_size-nw)//2
    y=int((canvas_size-nh)*0.55)

    alpha=Image.fromarray(obj_mask).convert("L")
    obj_rgba=obj.convert("RGBA")

    if background=="white":
        canvas.paste(obj_rgba.convert("RGB"),(x,y),alpha)
    else:
        canvas.paste(obj_rgba,(x,y),alpha)

    return canvas, {"x":x,"y":y,"w":nw,"h":nh,"mask":obj_mask}

def add_shadow(img, rect, shadow_opts, bg):
    if rect is None or not shadow_opts.get("enabled",True): return img
    if bg!="white": return img
    x,y,w,h,mask=rect["x"],rect["y"],rect["w"],rect["h"],rect["mask"]
    arr=np.array(img).astype(np.float32)
    H,W=arr.shape[:2]
    k=np.ones((3,3),np.uint8)
    sh=cv2.erode(mask.astype(np.uint8),k,1)
    sh_canvas=np.zeros((H,W),dtype=np.uint8)

    dx,dy=shadow_opts["offset"]["x"],shadow_opts["offset"]["y"]
    x1,y1=max(0,x+dx),max(0,y+dy)
    x2,y2=min(W,x1+w),min(H,y1+h)
    sh_canvas[y1:y2,x1:x2]=sh[0:(y2-y1),0:(x2-x1)]

    blur=shadow_opts["blur"]
    ksize=blur if blur%2==1 else blur+1
    sh_bl=cv2.GaussianBlur(sh_canvas,(ksize,ksize),0)
    intensity=shadow_opts["intensity"]
    alpha=sh_bl/255.0*intensity

    for c in range(3):
        arr[:,:,c]=(1-alpha)*arr[:,:,c]

    return Image.fromarray(arr.astype(np.uint8))

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/process")
async def process(file: UploadFile=File(...), options: str=Form(None)):
    try:
        fb=await file.read()
        opts=merge_options(json.loads(options) if options else None)

        img=load_and_preprocess_image(fb,opts["max_size"])
        pre=preprocess_for_segmentation(img)
        mask=get_refined_mask(pre)

        composed,rect=compose_foreground(img,mask,opts["background"],opts["max_size"])
        composed=add_shadow(composed,rect,opts["shadow"],opts["background"])

        name=file.filename.rsplit('.',1)[0]
        if opts["background"]=="transparent":
            bio=io.BytesIO()
            composed.save(bio,format="PNG")
            out=bio.getvalue()
            return Response(out,media_type="image/png",headers={"X-Output-Filename":f"{name}_bg_shadow.png"})
        else:
            bio=io.BytesIO()
            composed.convert("RGB").save(bio,format="JPEG",quality=88)
            out=bio.getvalue()
            return Response(out,media_type="image/jpeg",headers={"X-Output-Filename":f"{name}_bg_shadow.jpg"})
    except Exception as e:
        return Response(json.dumps({"error":str(e)}),media_type="application/json",status_code=500)
