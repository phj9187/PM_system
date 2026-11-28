from pathlib import Path
from html import escape

OUT=Path(__file__).parent/'designs'
OUT.mkdir(exist_ok=True)
C=dict(bg='#F5F7FA',ink='#1B303D',muted='#71828E',grid='#EAF0F3',line='#D7E1E7',blue='#366AF0',teal='#218A7A',amber='#AD6A18',white='#FFFFFF')
def make(detail=False):
    s=['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1020" viewBox="0 0 1440 1020">']
    def rect(x,y,w,h,c,r=0,stroke=None):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{C.get(c,c)}"'+(f' stroke="{C.get(stroke,stroke)}"' if stroke else '')+'/>')
    def text(x,y,t,size=14,c='ink',weight=400):
        s.append(f'<text x="{x}" y="{y}" font-family="Noto Sans KR, Malgun Gothic, sans-serif" font-size="{size}" font-weight="{weight}" fill="{C.get(c,c)}">{escape(t)}</text>')
    def line(x,y,x2,y2,c='line',w=1):
        s.append(f'<path d="M{x} {y} L{x2} {y2}" fill="none" stroke="{C.get(c,c)}" stroke-width="{w}" stroke-linecap="round"/>')
    rect(0,0,1440,1020,'bg');rect(0,0,1440,68,'white');line(0,68,1440,68)
    rect(28,21,24,24,'teal',7);text(66,41,'PM System',19,'ink',700)
    text(244,41,'운영 대시보드',14,'blue',700);text(397,41,'프로젝트',13,'muted');text(502,41,'기록',13,'muted')
    text(1070,40,'샘플 프로젝트 · 예시 데이터',11,'muted');rect(1287,18,120,34,'ink',7);text(1320,40,'공유하기',12,'white')
    text(32,98,'WORKSPACE  /  조직 운영 시스템',11,'muted');text(32,138,'프로젝트 타임라인',28,'ink',700)
    text(1190,132,'마지막 갱신  11.18 14:30',11,'muted')
    rect(32,162,800,158,'white',12,'line');text(56,191,'PROJECT NORTH STAR',10,'teal',700)
    text(56,225,'팀의 흐름을 한눈에, 필요한 판단은 제때',22,'ink',700)
    text(56,252,'목표  업무·자원·결정 정보를 연결한 운영 대시보드 첫 버전 완성',13,'muted')
    text(56,276,'성공 조건  팀원 5명 시험 운영 · 핵심 현황과 결정 요청을 쉽게 확인',12,'muted')
    text(56,300,'최종 기한  2026.12.07     /     프로젝트 매니저  김민서',12)
    rect(852,162,556,158,'white',12,'line');text(876,192,'지금 확인할 정보',14,'ink',700)
    text(876,229,'결정 대기 02',24,'amber',700);text(1082,229,'진행 장애 01',24,'ink',700)
    text(876,259,'11.19까지  시험 운영 범위 확정',13);text(876,283,'담당자 확인 필요  데이터 연결 작업',12,'muted')
    text(876,305,'항목을 선택하면 관련 작업으로 이동',10,'muted')
    text(32,360,'상세 보기  /  11.16 — 11.23' if detail else '전체 보기  /  11.09 — 12.07',14,'ink',700)
    for x,t,c in [(550,'완료','teal'),(625,'진행 중','blue'),(715,'예정','muted'),(790,'결정 필요','amber')]:
        rect(x,350,6,6,c,3);text(x+13,358,t,11,'muted')
    text(1006,359,'오늘로 이동',12,'blue');rect(1110,335,212,37,'white',8,'line')
    text(1127,359,'−',18);text(1186,359,'200%' if detail else '100%',12,'blue');text(1288,359,'+',18);text(1340,359,'전체 맞춤',11,'muted')
    rect(0,386,1440,563,'white');line(0,386,1440,386)
    start=60;step=176 if detail else 46;days=7 if detail else 28;base=16 if detail else 9
    for d in range(days+1):
        x=start+d*step
        line(x,436,x,933,'line' if d%7==0 else 'grid')
        line(x,427,x,436,'line')
        if detail or d%2==0:
            n=base+d;date=f'11.{n:02}' if n<=30 else f'12.{n-30:02}'
            text(x-16,416,date,11,'muted')
    now=start+(2 if detail else 9)*step
    line(now,434,now,933,'blue',1.5);rect(now-30,391,66,26,'blue',6);text(now-21,409,'오늘 18일',10,'white')
    line(32,668,1408,668,'line',3);text(32,643,'현재 단계 / 화면 설계' if detail else 'PROJECT FLOW',10,'muted')
    def node(d,t):
        x=start+d*step;s.append(f'<circle cx="{x}" cy="668" r="6" fill="white" stroke="{C["blue"]}" stroke-width="2.5"/>');text(x-22,698,t,11,'muted')
    def task(d,e,y,title,status,person,desc,dates,c):
        x=start+d*step;end=start+e*step;h=112
        line(x,668,x,y+h if y<668 else y,c,1.6)
        rect(x,y,220,h,'white',10,'line');rect(x,y+13,3,20,c,1)
        text(x+16,y+23,status,10,c,700);text(x+16,y+48,title,15,'ink',700)
        text(x+16,y+70,dates+' · '+person,10,'muted');text(x+16,y+94,desc,11,'muted')
        line(x,y+h+11,end,y+h+11,c,4)
        line(end,y+h+6,end,y+h+16,c,1.5)
    if not detail:
        for d,t in [(0,'착수'),(4,'범위 확정'),(9,'설계 시작'),(14,'개발 시작'),(21,'시험 운영'),(28,'첫 버전 완료')]:node(d,t)
        task(0,4,471,'목표·요구사항 정리','완료','김민서','운영 기준과 핵심 요구 확정','11.09 — 11.13','teal')
        task(4,9,755,'사용자 흐름 설계','완료','박지훈','주요 화면과 사용 순서 정리','11.13 — 11.18','teal')
        task(9,14,471,'타임라인 UI 설계','진행 중','이서연','시간 눈금과 가지 구조 설계','11.18 — 11.23','blue')
        task(10,18,755,'데이터 구조·연결','담당 확인 필요','미정','일정 영향 검토 필요','11.19 — 11.27','amber')
        task(14,21,471,'핵심 화면 개발','예정','개발팀','디자인 확정 후 착수','11.23 — 11.30','muted')
        task(21,28,755,'시험 운영·개선','예정','팀 전체','팀원 5명 대상 사용성 확인','11.30 — 12.07','muted')
    else:
        for d,t in [(0,'설계 준비'),(2,'화면 설계'),(7,'개발 인계')]:node(d,t)
        task(0,2,471,'요구사항 검토','완료','김민서','작업·일정 표시 기준 정리','11.16 — 11.18','teal')
        task(2,5,471,'타임라인 구조 설계','진행 중','이서연','눈금·분기·정보 밀도 검토','11.18 — 11.21','blue')
        task(2,4,755,'고정 정보 패널 설계','진행 중','박지훈','목표와 결정 요청 표시','11.18 — 11.20','blue')
        task(4,6,471,'팀원 의견 수렴','예정','김민서','시안 확인 후 주요 이견 정리','11.20 — 11.22','muted')
        task(5,7,755,'시안 보완·개발 인계','예정','이서연','화면 상태와 동작 기준 전달','11.21 — 11.23','muted')
    line(0,949,1440,949);text(32,985,'드래그하여 이동  ·  확대하면 세부 작업과 진행 정보 표시',11,'muted')
    text(780,985,'예시 데이터',10,'muted');line(960,981,1385,981,'line',3)
    rect(1100 if detail else 960,975,105 if detail else 425,12,'blue',5)
    s.append('</svg>')
    p=OUT/('02-detail.svg' if detail else '01-overview.svg');p.write_text('\n'.join(s),encoding='utf-8');print(p)
make();make(True)
