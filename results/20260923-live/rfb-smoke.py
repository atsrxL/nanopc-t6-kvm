import socket,ssl,struct,json,time
from pathlib import Path
def recv(s,n):
 b=b''
 while len(b)<n:
  v=s.recv(n-len(b))
  if not v: raise EOFError()
  b+=v
 return b
def connect(password):
 s=socket.create_connection(('127.0.0.1',5900),timeout=8)
 assert recv(s,12)==b'RFB 003.008'+bytes([10]);s.sendall(b'RFB 003.008'+bytes([10]))
 n=recv(s,1)[0];assert recv(s,n)==bytes([19]);s.sendall(bytes([19]))
 assert recv(s,2)==bytes([0,2]);s.sendall(bytes([0,2]));assert recv(s,1)==bytes([0])
 n=recv(s,1)[0];sub=struct.unpack('!'+str(n)+'I',recv(s,4*n));assert sub==(262,)
 s.sendall(struct.pack('!I',262));assert recv(s,1)==bytes([1])
 ctx=ssl.create_default_context(cafile='/etc/t6-kvm/vnc.crt')
 s=ctx.wrap_socket(s,server_hostname='192.168.123.99')
 u=b'operator';p=password.encode();s.sendall(struct.pack('!II',len(u),len(p))+u+p)
 result=struct.unpack('!I',recv(s,4))[0]
 if result:
  size=struct.unpack('!I',recv(s,4))[0];recv(s,size);s.close();return None
 s.sendall(bytes([1]));header=recv(s,24);w,h=struct.unpack('!HH',header[:4]);size=struct.unpack('!I',header[20:])[0];recv(s,size)
 enc=[50,7,-223,-308,-32];s.sendall(struct.pack('!BBH',2,0,len(enc))+struct.pack('!'+str(len(enc))+'i',*enc))
 s.sendall(struct.pack('!BBHHHH',3,0,0,0,w,h))
 return s
password=Path('/root/t6-kvm-operator-password').read_text().strip()
a=connect(password);assert a
assert connect('intentional-invalid-password') is None
# A remains connected after failed authentication; read actual server update.
first=recv(a,1);assert first==bytes([0]),first
print(json.dumps({'tls_certificate_verified':True,'only_x509plain':True,'valid_auth':True,'invalid_auth_rejected':True,'old_client_survives_wrong_password':True,'framebuffer_update_received':True}))
time.sleep(3)
b=connect(password);assert b
# Drain prior framebuffer messages until authenticated takeover closes A.
a.settimeout(8)
closed=False
try:
 while a.recv(65536):pass
 closed=True
except (ConnectionResetError,ssl.SSLEOFError):closed=True
assert closed,'old controller not closed'
print(json.dumps({'authenticated_takeover':True}))
time.sleep(8)
b.close();a.close()
