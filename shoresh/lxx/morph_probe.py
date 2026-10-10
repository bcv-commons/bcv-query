import sqlite3, collections, difflib, re, sys
sys.path.insert(0, ".")
a=sqlite3.connect("lxx/lxx.db"); b=sqlite3.connect("lxx/data/lxx-glaux.db")
def key(p): return p.lower().replace("ς","σ").rstrip("ν")
def load(c, lem=False):
    d=collections.defaultdict(list)
    for r in c.execute("select book,chapter,verse,plain,morph,pos from lxx_words order by book,chapter,verse,idx"):
        d[(r[0],r[1],r[2])].append((key(r[3]),r[4],r[5]))
    return d
A,B=load(a),load(b)
NOMINAL=re.compile(r"^(?P<c>[NGDAV])?(?P<n>[SPD])?(?P<g>[MFN])?$")
def feats(pos, m):
    s=m.split(".",1)[1] if "." in m else ""
    if pos in ("N","A","RA","RD","RP","RR","RI","RX"):
        x=NOMINAL.match(s)
        return dict(case=x.group("c"),number=x.group("n"),gender=x.group("g")) if x else None
    if pos=="V":
        if len(s)>=3 and s[2]=="P": # participle: T V P C N G
            y=re.match(r"^([PIFAXY]F?)([AMP])P([NGDAV])?([SPD])?([MFN])?$",s)
            return dict(tense=y.group(1),voice=y.group(2),mood="P",case=y.group(3),number=y.group(4),gender=y.group(5)) if y else None
        y=re.match(r"^([PIFAXY]F?)([AMP])([ISODNM])([123])?([SPD])?$",s)
        return dict(tense=y.group(1),voice=y.group(2),mood=y.group(3),person=y.group(4),number=y.group(5)) if y else None
    return {}
diff=collections.Counter(); both=collections.Counter(); miss_new=collections.Counter(); miss_old=collections.Counter()
by_pos=collections.defaultdict(collections.Counter)
examples=collections.defaultdict(list)
n_same_pos=0; n_unparsed=0
for k in set(A)&set(B):
    sm=difflib.SequenceMatcher(None,[i[0] for i in A[k]],[i[0] for i in B[k]],autojunk=False)
    for blk in sm.get_matching_blocks():
        for t in range(blk.size):
            o,n=A[k][blk.a+t],B[k][blk.b+t]
            if o[2]!=n[2] or o[2] in ("P","D","C","X","M","I"): continue
            n_same_pos+=1
            fo,fn=feats(o[2],o[1]),feats(n[2],n[1])
            if fo is None or fn is None: n_unparsed+=1; continue
            same_all=True
            for f in set(fo)|set(fn):
                vo,vn=fo.get(f),fn.get(f)
                if vo and vn:
                    both[f]+=1
                    if vo!=vn:
                        diff[f]+=1; by_pos[o[2]][f]+=1; same_all=False
                        if len(examples[f])<4 and (len(examples[f])==0 or not any(e.startswith(k[0]) for e in examples[f])): examples[f].append(f"{k[0]} {k[1]}:{k[2]} {o[1]}→{n[1]}")
                elif vo and not vn: miss_new[f]+=1
                elif vn and not vo: miss_old[f]+=1
print("same-POS inflected words compared:",n_same_pos,"unparsed:",n_unparsed)
print("feature  both-have  differ  differ%  | only old has  only new has")
for f in ("case","number","gender","tense","voice","mood","person"):
    print(f"{f:7} {both[f]:8} {diff[f]:7} {100*diff[f]/max(both[f],1):5.1f}%  | {miss_new[f]:6} {miss_old[f]:6}   {examples[f][:3]}")
print("differences per POS:",{p:dict(c.most_common(3)) for p,c in by_pos.items()})
# internal consistency: article directly followed by noun/adjective must agree in case, number, gender
def concord(D):
    ok=tot=0; bad=[]
    for k,ws in D.items():
        for i in range(len(ws)-1):
            x,y=ws[i],ws[i+1]
            if x[2]=="RA" and y[2] in ("N","A"):
                fx,fy=feats("RA",x[1]),feats(y[2],y[1])
                if not fx or not fy or not (fx.get("case") and fy.get("case") and fx.get("number") and fy.get("number")): continue
                g_ok = (not fx.get("gender") or not fy.get("gender") or fx["gender"]==fy["gender"])
                tot+=1
                good = fx["case"]==fy["case"] and fx["number"]==fy["number"] and g_ok
                ok+=good
                if not good and len(bad)<3: bad.append((k,x[1],y[1]))
    return ok,tot,bad
for name,D in (("old (CATSS)",A),("new (GLAUx)",B)):
    ok,tot,bad=concord(D); print(f"article+noun/adjective agree in case, number, gender: {name}: {ok}/{tot} = {100*ok/tot:.2f}%  e.g. disagreements {bad[:2]}")
# genesis (hand-checked in GLAUx) vs the rest
def concord_book(D,books):
    Dsub={k:v for k,v in D.items() if (k[0] in books)}
    return concord(Dsub)
for label,bs in (("GEN (hand-checked in GLAUx)",{"GEN"}),("rest",set(k[0] for k in A)-{"GEN"})):
    for name,D in (("old",A),("new",B)):
        ok,tot,_=concord_book(D,bs); print(f"  {label:28} {name}: {100*ok/tot:.2f}% ({tot})")

print("\n--- where the new store has fewer features")
cnt=collections.Counter(); ex=collections.defaultdict(list); lemc=collections.Counter()
bl=sqlite3.connect("lxx/data/lxx-glaux.db")
L=collections.defaultdict(list)
for r in bl.execute("select book,chapter,verse,lemma from lxx_words order by book,chapter,verse,idx"): L[(r[0],r[1],r[2])].append(r[3])
tot_words=0; fewer=0
for k in set(A)&set(B):
    sm=difflib.SequenceMatcher(None,[i[0] for i in A[k]],[i[0] for i in B[k]],autojunk=False)
    for blk in sm.get_matching_blocks():
        for t in range(blk.size):
            o,n=A[k][blk.a+t],B[k][blk.b+t]
            if o[2]!=n[2] or o[2] not in ("N","A","RA","RD","RP","RR","RI","RX"): continue
            fo,fn=feats(o[2],o[1]),feats(n[2],n[1])
            if not fo or not fn: continue
            tot_words+=1
            lost=[f for f in ("case","number","gender") if fo.get(f) and not fn.get(f)]
            if lost:
                fewer+=1; cnt[(o[2],tuple(lost))]+=1; lemc[L[k][blk.b+t]]+=1
                if len(ex[(o[2],tuple(lost))])<3: ex[(o[2],tuple(lost))].append(f"{k[0]} {k[1]}:{k[2]} {L[k][blk.b+t]} {o[1]}→{n[1]}")
print("nominal words compared:",tot_words,"; new lacks a feature that old has on:",fewer,f"({100*fewer/tot_words:.1f}%)")
for (p,l),c in cnt.most_common(8): print(f"  {p} lacking {','.join(l)}: {c}  e.g. {ex[(p,l)][:2]}")
print("most affected lemmas:",lemc.most_common(14))
# how many of those are proper names (capitalised lemma)
names=sum(c for l,c in lemc.items() if l and l[0].isupper()); print("share with a capitalised lemma (names):",f"{100*names/fewer:.0f}%")
