# Deploy บน Rancher

สิ่งเดียวที่ต้องจำ: **ข้อมูลทั้งหมดอยู่ที่ `/data` ใน container ต้องผูก volume ถาวร (PVC) ไว้ที่นั่น** ไม่อย่างนั้นข้อมูลจะหายเมื่อ pod ถูกสร้างใหม่

มี 2 วิธี เลือกวิธีเดียว:
- **วิธี A — Import YAML (เร็วที่สุด):** แก้ 4 จุดในไฟล์ แล้ววางใน Rancher
- **วิธี B — คลิกใน UI ทีละขั้น:** ถ้าอยากเห็นทุกค่าที่ตั้ง

> ชื่อเมนูอาจต่างกันเล็กน้อยตามเวอร์ชัน Rancher (คู่มือนี้อิงหน้า Cluster Explorer ของ Rancher 2.6 ขึ้นไป)

---

## ขั้นที่ 0: สร้าง image แล้ว push ขึ้น registry ของบริษัท

ทำครั้งเดียวต่อเวอร์ชัน (หรือให้ CI ทำ) ที่โฟลเดอร์โปรเจกต์:

```bash
docker build -t registry.company.com/cahon:1.0 .
```

```bash
docker push registry.company.com/cahon:1.0
```

เปลี่ยน `registry.company.com` เป็น registry จริงของบริษัท

---

## วิธี A: Import YAML

1. เปิดไฟล์ [`deploy/rancher.yaml`](../deploy/rancher.yaml) แก้จุดที่เขียนว่า `CHANGE`:
   - `image:` → image ที่ push ไว้ในขั้นที่ 0
   - `CAHON_PASSWORD:` → รหัสผ่านสำหรับล็อกอินเข้าแอป
   - `host:` → ชื่อเว็บที่จะให้คนเปิด เช่น `search.company.com`
   - `storageClassName:` → (ไม่ใส่ก็ได้ จะใช้ค่าเริ่มต้นของ cluster) **ห้ามใช้ NFS** ถามทีม IT ว่าใช้ตัวไหน เช่น `longhorn`
2. ใน Rancher เข้า cluster → ปุ่ม **Import YAML** (มุมขวาบน)
3. เลือก namespace → วางเนื้อหาไฟล์ → **Import**
4. ไปที่ **Workloads → Deployments** รอให้ `cahon` เป็นสถานะ **Active**
5. เปิดชื่อเว็บที่ตั้งไว้ แล้วล็อกอินด้วยรหัสผ่านจากข้อ 1

---

## วิธี B: คลิกใน UI ทีละขั้น

### 1. สร้างที่เก็บข้อมูล (PVC)
**Storage → PersistentVolumeClaims → Create**
- Name: `cahon-data`
- Source: *Use a Storage Class to provision a new Persistent Volume*
- Storage Class: block storage ของ cluster (เช่น longhorn) — **ห้าม NFS** (ฐานข้อมูล SQLite บน NFS อาจเสียหายได้)
- Request Storage: `10` GiB
- Access Modes: **Single-Node Read/Write**

### 2. เก็บรหัสผ่าน (Secret)
**Storage → Secrets → Create → Opaque**
- Name: `cahon-secret`
- Key: `CAHON_PASSWORD` · Value: รหัสผ่านสำหรับล็อกอิน

### 3. สร้างตัวแอป (Deployment)
**Workloads → Deployments → Create**

| แท็บ / หัวข้อ | ตั้งค่า |
|---|---|
| Name | `cahon` |
| Replicas | **1** (ต้องเป็น 1 เท่านั้น) |
| Container Image | image จากขั้นที่ 0 |
| Ports → Add Port | Name `http`, Private Container Port `8765`, TCP, Service Type **Cluster IP** |
| Environment Variables → Add Variable | Type **Secret key**: Variable `CAHON_PASSWORD` ← secret `cahon-secret` key `CAHON_PASSWORD` |
| Environment Variables → Add Variable | Type Key/Value: `CAHON_HTTPS_COOKIE` = `1` (ถ้าเข้าเว็บผ่าน HTTPS) |
| Resources | CPU Reservation `250m`, CPU Limit `2000m`, Memory Reservation `512Mi`, **Memory Limit `1536Mi`** |
| Health Check | Readiness และ Liveness: HTTP request, Path `/api/status`, Port `8765` |
| Storage → Add Volume → Persistent Volume Claim | เลือก `cahon-data`, Mount Point **`/data`** |
| Pod → Security Context | **Filesystem Group: `10001`** (ถ้าไม่ตั้ง แอปจะเขียนลง volume ไม่ได้) |
| Deployment → Scaling and Upgrade Policy | **Recreate** (*Kill ALL pods and then start new pods*) |

กด **Create** แล้วรอสถานะ **Active**

### 4. เปิดให้เข้าจากเว็บ (Ingress)
**Service Discovery → Ingresses → Create**
- Request Host: `search.company.com`
- Path: Prefix `/` → Target Service: service ของแอป (ชื่อที่ Rancher สร้างให้ในข้อ 3) → Port `8765`
- Certificates: ใส่ TLS secret ถ้ามี
- ถ้าจะอัปโหลดไฟล์ใหญ่: Labels & Annotations → `nginx.ingress.kubernetes.io/proxy-body-size` = `200m`

---

## เช็กว่าข้อมูลไม่หาย

1. ล็อกอิน → เพิ่มโน้ตสักอัน
2. ใน Rancher: Deployment `cahon` → เมนู **⋮ → Redeploy**
3. รอ Active แล้วเปิดเว็บใหม่ → โน้ตต้องยังอยู่

---

## ถ้ามีปัญหา

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| pod ขึ้น error `cannot write to the data folder /data` | ยังไม่ได้ตั้ง **Filesystem Group = 10001** (ข้อ 3) |
| `server mode needs a login password` | ยังไม่ได้ผูก `CAHON_PASSWORD` จาก Secret (ข้อ 3) |
| pod ใหม่ค้างที่ *ContainerCreating* ตอน redeploy | ยังเป็น Rolling update อยู่ ให้เปลี่ยนเป็น **Recreate** |
| pod ถูก restart ด้วย *OOMKilled* | Memory Limit ต่ำไป ให้เพิ่มเป็นอย่างน้อย `1536Mi` |
| อัปโหลดไฟล์ใหญ่แล้วขึ้น 413 | เพิ่ม annotation `proxy-body-size` ใน Ingress |

## อยากให้ค้นไฟล์จาก file server ของบริษัทด้วย
mount โฟลเดอร์นั้นเข้า pod แบบ **read-only** (ตรงนี้ใช้ NFS ได้ เพราะแอปแค่อ่าน) เช่นที่ `/files` แล้วเพิ่ม Environment Variable `CAHON_FOLDERS` = `/files`

## แอปรู้ limit ของ pod เอง
แอปอ่าน CPU/Memory limit ของ container แล้วปรับขีดจำกัดการสแกนให้อยู่ในงบของ pod เอง ดูได้ในหน้า ตั้งค่า → การสแกนไฟล์ ไม่ต้องตั้งเพิ่ม
