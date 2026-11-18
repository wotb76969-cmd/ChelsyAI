"""Exercise an actual isolated renderer with 50 typed inputs and independent parsers."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import sys
from docx import Document
from pptx import Presentation
from openpyxl import load_workbook
from pypdf import PdfReader
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mind.artifacts.render import render
from mind.artifacts.builder import ArtifactSpec

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    results=[]
    topics=['Аудитория','Расписание','Договорённости','Список закупок','Экскурсия','Транспорт','Выставка','Расходы','Команда','Регистрация']
    for fmt in ['txt','docx','pdf','pptx','xlsx']:
        for i,topic in enumerate(topics):
            title=topic+' — план семинара'
            units=3 if fmt=='docx' else 8 if fmt=='pptx' else 2
            sections=[{'heading':h,'paragraphs':[v],'bullets':['Запишите ответственного и дату проверки.']} for h,v in [
                (topic,'До встречи проверьте список участников и подтвердите число мест.'),
                ('В день семинара','Сверьте расписание с командой и согласуйте время перерыва.'),
                ('После встречи','Сохраните решения и сообщите участникам сроки выполнения.')]][:units]
            fmt_slides=[{'title':s,'bullets':[t],'notes':'Спросите у команды, кто выполнит это действие.'} for s,t in zip(['Цель','Участники','Место','Материалы','Занятие','Перерыв','Обратная связь','Итоги'],['Согласовать ожидаемый результат.','Уточнить состав группы.','Проверить доступность зала.','Раздать программу.','Разобрать практический пример.','Соблюсти расписание.','Собрать вопросы.','Подвести итоги.'])]
            tables=[{'headers':['Статья','Количество','Сумма, ₽'],'rows':[['Раздаточные материалы',4+i,400+i*100],['Аренда',1,1200+i*10]],'add_total':True}]
            with tempfile.TemporaryDirectory() as tmp:
                built=render(ArtifactSpec(fmt,title,'ru',sections,tables=tables if fmt=='xlsx' else None,slides=fmt_slides if fmt=='pptx' else None),Path(tmp))
                p=built.path
                if fmt=='txt':assert title in p.read_text(encoding='utf8')
                elif fmt=='docx':assert len(Document(p).element.xpath('.//w:br[@w:type="page"]'))==2 and any(t.text==title for t in Document(p).paragraphs)
                elif fmt=='pdf':
                    pdf=PdfReader(p);assert len(pdf.pages)==2 and topic in pdf.pages[0].extract_text()
                elif fmt=='pptx':
                    slides=Presentation(p).slides;assert len(slides)==8 and slides[0].notes_slide.notes_text_frame.text
                else:
                    wb=load_workbook(p);ws=wb.active;assert ws['C4'].value=='=SUM(C2:C3)' and ws['C2'].data_type=='n' and ws['C3'].value==1200+i*10
                results.append(dict(case=f'{fmt}-{i+1}',passed=True,bytes=built.size_bytes,sha256=built.sha256))
                if i==0:(args.out/('seminar.'+fmt)).write_bytes(p.read_bytes())
    (args.out/'checks.json').write_text(json.dumps(results,indent=2))
    print(len(results),'passed')
if __name__=='__main__':main()
