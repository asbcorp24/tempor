import os,sys,sqlite3,datetime,threading,time,webbrowser,urllib.request,xml.etree.ElementTree as ET
from flask import Flask,request,redirect,jsonify,render_template
from werkzeug.utils import secure_filename
BASE=os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys,'frozen',False) else os.path.dirname(os.path.abspath(__file__))
ASSETS=getattr(sys,'_MEIPASS',BASE)
DB=os.environ.get('SCHEDULE_DB',os.path.join(BASE,'schedule.db'))
app=Flask(__name__,template_folder=os.path.join(ASSETS,'templates'));app.config['MAX_CONTENT_LENGTH']=30*1024*1024

def connect():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c

def init():
 with connect() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,name TEXT); CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY,group_id INTEGER,day INTEGER,hour INTEGER,subject TEXT,teacher TEXT,room TEXT,start TEXT,end TEXT,subgroup INTEGER DEFAULT 0); CREATE INDEX IF NOT EXISTS ix_lessons ON lessons(group_id,day,start,end); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);''')
  if 'subgroup' not in [r[1] for r in c.execute('PRAGMA table_info(lessons)')]:c.execute('ALTER TABLE lessons ADD COLUMN subgroup INTEGER DEFAULT 0')

def val(el,path,default=''):
 return el.findtext(path,default=default) if el is not None else default

def iso(s):
 try:return datetime.datetime.strptime(s,'%d.%m.%Y').date().isoformat()
 except:return ''

def import_xml(path):
 root=ET.parse(path).getroot()
 if root.tag!='timetable':raise ValueError('Ожидается XML Ректор-Колледж (timetable)')
 groups={int(val(e,'id')):val(e,'name') for e in root.findall('classes/class')}
 subjects={int(val(e,'id')):val(e,'full_name') or val(e,'short_name') for e in root.findall('subjects/subject')}
 rooms={int(val(e,'id')):val(e,'name') for e in root.findall('rooms/room')}
 teachers={int(val(e,'person/id')):' '.join(filter(None,[val(e,'person/surname'),val(e,'person/first_name'),val(e,'person/second_name')])) for e in root.findall('teachers/teacher')}
 loads={}
 for e in root.findall('loads/load'):
  lid=int(val(e,'id')); klass=[int(x.text) for x in e.findall('klass_id_list/int') if x.text];parts=[]
  for g in e.findall('groups/group'):
   parts.append((subjects.get(int(val(g,'subject_id','-1')),''),teachers.get(int(val(g,'teacher_id','-1')),'')))
  loads[lid]=(klass,parts)
 rows=[]
 for e in root.findall('scheds/sched'):
  lid=int(val(e,'load_id','-1')); group_idx=int(val(e,'group','0')); record=loads.get(lid)
  if not record:continue
  klass,parts=record
  if not parts:continue
  subject,teacher=parts[min(max(group_idx,0),len(parts)-1)]
  for klass_id in klass:
   if klass_id in groups:
    rows.append((klass_id,int(val(e,'day','0')),int(val(e,'hour','0')),subject,teacher,rooms.get(int(val(e,'room_id','-1')),''),iso(val(e,'begin_date')),iso(val(e,'end_date')),group_idx+1 if len(parts)>1 else 0))
 times=[(x.text or '').strip() for x in root.findall('times/time')]
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM lessons');c.execute('DELETE FROM groups')
  c.executemany('INSERT INTO groups(id,name) VALUES(?,?)',groups.items())
  c.executemany('INSERT INTO lessons(group_id,day,hour,subject,teacher,room,start,end,subgroup) VALUES(?,?,?,?,?,?,?,?,?)',rows)
  for k,v in {'updated':datetime.datetime.now().isoformat(timespec='seconds'),'count':str(len(rows)),'times':'|'.join(times),'period_start':val(root,'term/begin_date'),'period_end':val(root,'term/end_date')}.items():c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(k,v))
 return len(groups),len(rows)

@app.get('/')
def home():return redirect('/tv')
@app.route('/admin',methods=['GET','POST'])
def admin():
 message=''
 if request.method=='POST':
  f=request.files.get('file')
  if not f or not f.filename.lower().endswith('.xml'):message='Выберите XML-файл.'
  else:
   import tempfile
   with tempfile.NamedTemporaryFile(suffix='.xml',delete=False) as tmp:
    f.save(tmp);path=tmp.name
   try:
    n,m=import_xml(path);message=f'Загружено: {n} групп, {m} записей.'
   except Exception as ex:message='Ошибка импорта: '+str(ex)
   finally:os.unlink(path)
 with connect() as c: meta=dict(c.execute('SELECT key,value FROM meta').fetchall())
 return render_template('admin.html',message=message,meta=meta)
@app.get('/api/schedule')
def schedule():
 date=request.args.get('date') or datetime.date.today().isoformat()
 try:d=datetime.date.fromisoformat(date)
 except:return jsonify(error='Некорректная дата'),400
 with connect() as c:
  groups=[dict(x) for x in c.execute('SELECT * FROM groups ORDER BY name COLLATE NOCASE')]
  rows=[dict(x) for x in c.execute('SELECT group_id,day,hour,subject,teacher,room FROM lessons WHERE day=? AND start<=? AND end>=? ORDER BY group_id,hour',(d.isoweekday(),date,date))]
  meta=dict(c.execute('SELECT key,value FROM meta').fetchall())
 for g in groups:g['lessons']=[x for x in rows if x['group_id']==g['id']]
 return jsonify(date=date,groups=groups,times=meta.get('times','').split('|'),updated=meta.get('updated',''))
@app.get('/api/week')
def week():
 date=request.args.get('date') or datetime.date.today().isoformat()
 try:d=datetime.date.fromisoformat(date)
 except:return jsonify(error='Некорректная дата'),400
 monday=d-datetime.timedelta(days=d.weekday())
 sunday=monday+datetime.timedelta(days=6)
 with connect() as c:
  groups=[dict(x) for x in c.execute('SELECT * FROM groups ORDER BY name COLLATE NOCASE')]
  rows=[dict(x) for x in c.execute('SELECT group_id,day,hour,subject,room,subgroup,start,end FROM lessons WHERE start<=? AND end>=? AND day BETWEEN 1 AND 7 ORDER BY group_id,day,hour,subgroup',(sunday.isoformat(),monday.isoformat()))]
  meta=dict(c.execute('SELECT key,value FROM meta').fetchall())
 by_group={g['id']:g for g in groups}
 for g in groups:g['days']={str(i):[] for i in range(1,7)}
 for x in rows:
  day=x['day']
  if day>6 or x['group_id'] not in by_group:continue
  actual=monday+datetime.timedelta(days=day-1)
  if x['start']<=actual.isoformat()<=x['end']:
   by_group[x['group_id']]['days'][str(day)].append({k:x[k] for k in ('hour','subject','room','subgroup')})
 return jsonify(week_start=monday.isoformat(),week_end=sunday.isoformat(),groups=groups,times=meta.get('times','').split('|'),updated=meta.get('updated',''))
@app.get('/tv')
def tv():return render_template('tv.html')
init()
def open_tv_when_ready(port):
 url=f'http://localhost:{port}/tv'
 for _ in range(60):
  try:
   with urllib.request.urlopen(url,timeout=1) as response:
    if response.status==200:
     webbrowser.open(url,new=1)
     return
  except Exception:
   time.sleep(0.5)

if __name__=='__main__':
 port=int(os.environ.get('PORT','5000'))
 if os.environ.get('COLLEGE_TV_NO_BROWSER','').lower() not in ('1','true','yes'):
  threading.Thread(target=open_tv_when_ready,args=(port,),daemon=True).start()
 app.run(host='0.0.0.0',port=port,use_reloader=False)
