"""Проверка: ни одна горизонтальная/вертикальная линия не проходит через надпись (лист 1, поле чертежа). Запуск: python3 check_text_crossing.py out_1.400-15"""
import fitz,glob,re,sys,collections
pdfs=glob.glob(sys.argv[1]+'/*/*.pdf')
k=72/25.4; bad={}
for f in pdfs:
    pg=fitz.open(f)[0]
    words=[w for w in pg.get_text("words") if w[0]<228*k and w[1]>8*k]
    segs=[(it[1],it[2]) for d in pg.get_drawings() for it in d['items'] if it[0]=='l']
    for x0,y0,x1,y1,t,*_ in words:
        w,h=x1-x0,y1-y0
        if w*h<4: continue
        for a,b in segs:
            hor=abs(a.y-b.y)<0.1; ver=abs(a.x-b.x)<0.1
            if (hor and y0+h*0.25<a.y<y1-h*0.25 and min(a.x,b.x)<x0+w*0.4 and max(a.x,b.x)>x1-w*0.4) or \
               (ver and x0+w*0.25<a.x<x1-w*0.25 and min(a.y,b.y)<y0+h*0.4 and max(a.y,b.y)>y1-h*0.4):
                bad.setdefault(f.split('/')[-1],[]).append((t,round(x0/k),round(y0/k))); break
print('листов:',len(pdfs),'с линией через надпись:',len(bad))
print(collections.Counter(t[0] for v in bad.values() for t in v).most_common(12))
for kk,v in list(bad.items())[:12]: print(kk,v)
