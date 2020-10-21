#!/usr/bin/env python
import time
import pdb
import pickle
import os
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import GdkPixbuf
from gi.repository import Pango
from string import Template
import re
import datetime
import sys
from gi.repository import GtkSource

def show_error_dlg(error_string):
	"""This Function is used to show an error dialog when
	an error occurs.
	error_string - The error string that will be displayed
	on the dialog.
	"""
	error_dlg = Gtk.MessageDialog(type=Gtk.MessageType.ERROR
				, message_format=error_string
				, buttons=Gtk.ButtonsType.OK)
	error_dlg.run()
	error_dlg.destroy()


#import gc
#gc.set_debug(gc.DEBUG_LEAK)
#gc.enable()

homedir = os.path.expanduser('~')+"/"
icondir=scriptdir = "/".join(sys.argv[0].split('/')[:-1])+"/"
query_dir = homedir + "Queries"
prefsFile = homedir + ".sql-chump"

dbs = {}
try:
    class __odbc:
        id = "Sql Server (pyodbc + free tds)"
        api = __import__("pyodbc")
        conn_str = Template("Driver=freetds;UID=${Username};SERVER=${Server};DATABASE=${Database};TDS_Version=8.0;PORT=${Port};PWD=${password}")
        conn_fields = ["password","Username","Server","Database","Port"]
        show_tables_sql = "exec sp_tables"
        
        def select_db_name_sql(self):
            return "select DB_NAME()"

        def __init__(self):
            self.connection_parameters = {}

        def set_connection_param(self,k,v):
            if k in self.conn_fields:
                self.connection_parameters[k]=v
            return ""

        def show_tables_decode(self, r):
            return {'table':r[2],'owner':r[1],'type':r[3].lower()}

        def connect(self):
            return self.api.connect(self.conn_str.substitute(self.connection_parameters))

        def describe_connection(self):
            return Template("${Database} on ${Server}:${Port} (sqlserver)").safe_substitute(self.connection_parameters)

        def query_split(self,query):
            r = re.compile("^ *GO *$", re.IGNORECASE | re.MULTILINE)
            return r.split(query)

        def open_table_sql(self,owner,table):
            return "select * from " + owner + "." + table + "\n\nexec sp_help '" + owner + "." + table + "'\n\n "

    dbs[__odbc.id] = __odbc
    print("supporting ODBC")
except:
    print("no ODBC support")
    pass
          
try:
    class __mysql:
        id = "MySQL (MySQLdb)"
        api = __import__("pymysql")

        api.install_as_MySQLdb()
        conn_fields = ['passwd','host','db','user','port']
        show_tables_sql = "show tables"

        def select_db_name_sql(self):
            return  "select concat( database(), '@" + self.connection_parameters["host"] + "', ' mysql-chump')"

        def __init__(self):
            self.connection_parameters = {}

        def set_connection_param(self,k,v):
            if k in self.conn_fields:
                if k == 'port':
                    try:
                        v = int(v)
                    except Exception:
                        return "port must be a number"
                    v = int(v)
                self.connection_parameters[k]=v
            return ""

        def show_tables_decode(self,r):
            return {'table':r[0],'owner':'','type':'table'}

        def connect(self):
            return self.api.connect(**self.connection_parameters)

        def describe_connection(self):
            return Template("${db} on ${host}:${port} (mysql)").safe_substitute(self.connection_parameters)

        def query_split(self,query):
            return [query]

        def open_table_sql(self,owner,table):
            return "select * from " + owner + "." + table + ";\n\ndescribe " + table + "\n\n "

    dbs[__mysql.id] = __mysql
    print("supporting mysql")
except:
    print("no mysql support")
    pass

if len(dbs) == 0:
    show_error_dlg( "no python database bindings found\nYou need to install python-mysqldb for MySQL support or see http://code.google.com/p/sql-chump/wiki/Install to get odbc / MSSQL support")
    exit(1)


class ConnSetup:    
    connOk = False
    
    def __init__(self):     
        self.password_names = ["password","passwd"]
        self.drop_down_options = []        
        self.window=Gtk.Window(Gtk.WindowType.TOPLEVEL)
        self.window.connect("destroy", self.destroy)
        self.window.set_icon_from_file(icondir + "tray-connecting.png")
        self.accel_group = Gtk.AccelGroup()
        self.window.add_accel_group(self.accel_group)
        self.table = Gtk.Table(rows=20, columns=10, homogeneous=False) 
        ip = Gtk.Button("Connect")
        self.table.attach(ip,1,3,9,10)
        ip.connect("clicked", self.on_connect)
        key,mod = Gtk.accelerator_parse("Return")
        ip.add_accelerator("clicked",
                          self.accel_group,
                          key,
                          mod,
                          Gtk.AccelFlags.VISIBLE)            
        self.error_log = Gtk.Label()
        self.table.attach(self.error_log,1,3,10,11)
        
        lbl = Gtk.Label(label="Connection type")
        lbl.set_alignment(1,0.5)
        self.table.attach(lbl,0,1,1,2,xpadding=10)
        self.dbtype_combo = Gtk.ComboBoxText()
        self.table.attach(self.dbtype_combo,1,2,1,2)
        for k,v in dbs.items():
            #print("PK "), k
            self.dbtype_combo.append_text("new " + k + " connection" )
            self.drop_down_options.append(v())
        user_prefs = self.load_user_prefs()
        for i in range(0,len(user_prefs["saved_conn"])):
            db = user_prefs["saved_conn"][i]
            n = db.describe_connection()
            self.dbtype_combo.append_text(n)
            self.drop_down_options.append(db)
        self.dbtype_combo.set_active(0)
        self.dbtype_combo.connect("changed",self.redraw_connset)
        self.window.add(self.table)        
        self.menu_widgets = []
        if "last_used" in user_prefs:
            last_used = user_prefs["last_used"]
            #print("active "), last_used
            self.dbtype_combo.set_active(last_used)
        self.redraw_connset(None,True)

    def get_drop_down_value(self):
        return self.drop_down_options[self.dbtype_combo.get_active()]

    def redraw_connset(self,junk=None, dofocus=False):
        for widget in self.menu_widgets:
            self.table.remove(widget)
        self.menu_widgets = []
        table = self.table
        db = self.get_drop_down_value()
        fields = db.conn_fields
        i = 2
        self.ip_fields = {}        
        for key in fields:
            lbl = Gtk.Label(key.replace("_"," "))
            lbl.set_alignment(1,0.5)
            table.attach(lbl,0,1,i,i+1,xpadding=10)
            ip = Gtk.Entry()
            table.attach(ip,1,2,i,i+1)
            self.ip_fields[key] = ip
            i = i + 1
            self.menu_widgets.append(lbl)
            self.menu_widgets.append(ip)
        for n in self.password_names:
            if n in self.ip_fields:
                self.ip_fields[n].set_visibility(False) 
                if dofocus:
                    self.ip_fields[n].grab_focus()
        for k,v in db.connection_parameters.items():
            if k in self.ip_fields:
                self.ip_fields[k].set_text(str(v))
        self.window.show_all()        

    def destroy(self, widget, data=None):
        Gtk.main_quit()

    def on_connect(self, widget, data=None):
        db = self.get_drop_down_value()
        for k,v in self.ip_fields.items():
            rv = db.set_connection_param(k,v.get_text())
            if rv!="":
                self.tell_user(rv)
                return    
        self.save_prefs()
        try:
            conn = db.connect()
            conn.close()
            self.connOk = True
            self.db = db
            Gtk.main_quit()
        except Exception as detail:
            self.tell_user(str(detail))

    def tell_user(self,msg):
        m = ""
        for i in range(0,len(msg),60):
            m += msg[i:i+60]+"\n"
        self.error_log.set_text(m.strip())
                
    def load_user_prefs(self):
        prefs = None
        if os.path.exists(prefsFile):
            f = open(prefsFile,"r")
            try:
                prefs = pickle.load(f)
            except:
                self.tell_user("error loading connection prefs file")
            f.close()
        else:
            self.tell_user("no prefs file found")
        if prefs == None:
            prefs = {}
            prefs['saved_conn'] = []
        rv = []
        for setting in prefs['saved_conn']:
            hasset = False
            if not setting['dbtype'] in dbs.keys():
                continue
            db = dbs[setting['dbtype']]()
            for k,v in setting.items():
                if k != 'dbtype':
                    hasset = True
                db.set_connection_param(k,v)
            if hasset:
                rv.append(db)
        prefs["saved_conn"] = rv
        return prefs
 
    def save_prefs(self):
        prefs = {}
        prefs["saved_conn"] = []
        for db in self.drop_down_options:
            t ={}
            for k,v in db.connection_parameters.items():
                if k not in self.password_names:
                    t[k]=v
            t["dbtype"] = db.id
            prefs["saved_conn"].append(t)
        prefs["last_used"] = self.dbtype_combo.get_active()
        f = open(prefsFile,"w")
        pickle.dump(prefs,f)
        f.close()
        
    def main(self):
        Gtk.main()
        self.window.hide()
        if self.connOk:
            return self.db
        else:
            return None
        

class QueryResultSet():
    def __init__(self, clip, conn):
        self.tv = None
        self.ts = None
        self.row_count = 0
        self.selected_row = None
        self.selected_column = None
        self.data = None
        self.clip = clip
        self.conn = conn
        self.names = []

    def __del__(self):
        #print("delete everything")
        for r in self.data:
            for c in r:
                del c
        self.tv.get_parent().remove(self.tv)

    def pack_into(self, parent):
        parent.add(self.tv)

    def popup_copy_cell(self, menu_item):
        selected_rows = [r[0] for r in self.tv.get_selection().get_selected_rows()[1]]
        v = "\n".join([self.data[y][self.selected_col] for y in selected_rows])
        self.clip.set_text(v)
    
    def popup_copy_row(self, menu_item):
        selected_rows = [r[0] for r in self.tv.get_selection().get_selected_rows()[1]]
        op = ""
        for y in selected_rows:
            row = self.data[y]
            for col in row:
                op += str(col) + "\t"
            op += "\n"
        self.clip.set_text(op)
    
    def popup_copy_select(self, menu_item):
        selected_rows = [r[0] for r in self.tv.get_selection().get_selected_rows()[1]]
        op = ""
        for y in selected_rows:
            row = self.data[y]
            if(op!=""):
                op += " union "
            op += 'select ' + ",".join(["'" + str(col).replace("'","''") + "'" for col in row])            
            op += "\n"
        self.clip.set_text(op)
        
    def popup_copy_update(self, menu_item):
        #workout which table has been selected - only works if you select all columns from exactly one table 
        curs = self.conn.cursor()
        #find all tables containing columns named in results
        curs.execute("select name, id from syscolumns where name in ( " + ','.join(["'%s'"%name for name in self.names]) + ") ")
        d = curs.fetchone()
        tblcols = {}
        while(d!=None):
            col = d[0]
            tableId = d[1]
            if tableId in tblcols:
                tblcols[tableId].append(col)
            else:
                tblcols[tableId] = [col]
            d = curs.fetchone()        
        curs.close()                    
        pos_tables = []
        for id,cols in tblcols.items():
            if len(cols) != len(self.names):
                continue
            pos_tables.append(id)        
        if len(pos_tables) != 1:
            return #if more than one found, you could do a check against the query text to find the referenced table 
        curs = self.conn.cursor()
        curs.execute("select name from sysobjects where id = %s" % pos_tables[0])
        table_name = str(curs.fetchone()[0])
        curs.close()

        selected_rows = [r[0] for r in self.tv.get_selection().get_selected_rows()[1]]
        op = ""
        for y in selected_rows:
            row = self.data[y]
            op += 'update ' + table_name +' set '
            for i in range(1,len(self.names)-1):
                if i != 1:
                    op += ", "
                op += self.names[i] + "='" + row[i].replace("'","''") + "' "
            op += " where " + self.names[0] + "=" + row[0]
            op += "\n"
        self.clip.set_text(op)
          
    def init_tv(self, colTypes):
        self.ts = Gtk.ListStore(*colTypes)                        
        self.tv = Gtk.TreeView(self.ts)
        self.tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tv.set_rubber_banding(True)
        self.popup = Gtk.Menu()
        item = Gtk.MenuItem("copy column")
        item.connect("activate", self.popup_copy_cell)        
        self.popup.append(item)
        item = Gtk.MenuItem("copy rows")
        item.connect("activate", self.popup_copy_row)
        self.popup.append(item)
        item = Gtk.MenuItem("copy as sql select")
        item.connect("activate", self.popup_copy_select)
        self.popup.append(item)
        item = Gtk.MenuItem("copy as sql update")
        item.connect("activate", self.popup_copy_update)
        self.popup.append(item)
        self.popup.show_all()
        self.tv.connect("button-press-event", self.pop_pop)   

    def pop_pop(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = self.tv.get_path_at_pos(x, y)
            if pthinfo is None:
                return 1
            path, col, cellx, celly = pthinfo
            self.selected_row = path[0]
            self.selected_col = self.tv.get_columns().index(col)
            self.tv.grab_focus()
            self.popup.popup( None, None, None, event.button, time)
            return 1

    def read_data(self, curs):
        colTypes = []
        for i in curs.description:
            colTypes.append(str)        
        self.init_tv(colTypes)
        for i in range(len(curs.description)):                            
            name = curs.description[i][0]
            self.names.append(name)
            tvcol = Gtk.TreeViewColumn(name.replace("_","__"))
            cell = Gtk.CellRendererText()
            cell.set_fixed_height_from_font(2)
            tvcol.set_resizable(True)
            tvcol.pack_start(cell,True)
            self.tv.append_column(tvcol)
            tvcol.add_attribute(cell,'text',i)
        d = curs.fetchone()
        self.data = []
        while d!=None:
            self.row_count += 1
            row = []
            for col in d:
                if col == None:
                    row.append("")
                else:
                    row.append(str(col))
            self.ts.append(row)
            self.data.append(row)
            d = curs.fetchone()


class QueryW():
    def set_filename(self,filename):
        self.path = '/'.join(filename.split('/')[:-1])
        self.filename = filename.split('/')[-1]
        self.label.set_text(self.filename)
        self.original_text = self.get_query_text()
        
    def create_tab_label(self, title):
        self.tab_lbl = box = Gtk.HBox()
        self.label = Gtk.Label(label=title)
        closebtn = Gtk.Button()
        image = Gtk.Image()
        image.set_from_stock(Gtk.STOCK_CLOSE, Gtk.IconSize.MENU)
        closebtn.connect("clicked", self.close_tab, 1)        
        closebtn.set_image(image)
        closebtn.set_relief(Gtk.ReliefStyle.NONE)

        savebutton = Gtk.Button()
        image = Gtk.Image()
        image.set_from_stock(Gtk.STOCK_SAVE, Gtk.IconSize.MENU)
        savebutton.connect("clicked", self.file_save_and_close, 1)        
        savebutton.set_image(image)
        savebutton.set_relief(Gtk.ReliefStyle.NONE)


        box.pack_start(self.label, True, True)
        box.pack_end(savebutton, False, False)
        box.pack_end(closebtn, False, False)
        box.show_all()
        savebutton.hide()
        self.savebutton = savebutton
        return box 

    def undo(self):
        if self.textbuffer.can_undo():
            self.textbuffer.undo()

    def redo(self):
        if self.textbuffer.can_redo():
            self.textbuffer.redo()
        
    def textarea_enter_notify(self,buffon,tab=None):
        self.change_checked = False
        self.savebutton.hide()

    def close_tab(self,button,tab=None):
        if(self.file_has_changed()):
            if self.change_checked == False:
                box = self.tab_lbl
                self.change_checked = True
                self.savebutton.show()
                page_no = i = self.mainprog.apps.index(self)
                self.mainprog.notebook.set_current_page(page_no)
                return Gtk.ResponseType.CANCEL
        self.mainprog.close_tab(button,self)
        #if len(self.mainprog.apps) == 0:
        #    Gtk.main_quit()
        return Gtk.ResponseType.OK                

    def file_save_and_close(self,button,tab=None):
        self.file_save()
        self.mainprog.close_tab(button,self)
        
    def __init__(self,mainprog):
        self.conn = mainprog.conn
        self.db = mainprog.db
        self.mainprog = mainprog
        self.original_text = ""                                     
        self.filename = "New query " +str(len(mainprog.apps)+1)
        self.is_new_file = True        
        self.result_sets = []
        self.change_checked = False
        paned =  Gtk.VPaned()
        lbl = self.create_tab_label(self.filename)        
        mainprog.notebook.append_page(paned,lbl)        
        queryw = Gtk.ScrolledWindow()
        queryw.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        paned.pack1(queryw,True)
        self.textbuffer = GtkSource.Buffer()

        self.textview = GtkSource.View(buffer=self.textbuffer)        
        self.textview.modify_font(Pango.FontDescription("Courier New 16 bold"))
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD)

        #self.textview.connect("change?", self.textarea_enter_notify)
        queryw.add(self.textview)        
        self.result_win = Gtk.ScrolledWindow()
        self.result_win.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        paned.pack2(self.result_win,True)
        rbox = Gtk.VBox(False,1)
        self.result_win.add_with_viewport(rbox)
        paned.show_all()
        self.textview.grab_focus()
        mainprog.notebook.set_focus_child(self.textview)
            
    def file_has_changed(self):
        return not self.original_text == self.get_query_text()

    def file_save(self):
        if self.is_new_file:
            return self.file_saveas()
        f = open(self.path + "/" + self.filename,"w")
        f.write(self.get_query_text())
        f.close()
        self.original_text = self.get_query_text()
        self.mainprog.table_browser.refresh(self.conn,self.db)
        return Gtk.ResponseType.OK

    def file_saveas(self):
        dialog = Gtk.FileChooserDialog(
            title="Save query as",
            action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL,
                    Gtk.ResponseType.CANCEL,
                    Gtk.STOCK_SAVE,
                    Gtk.ResponseType.OK))
        dialog.set_default_response(Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename().strip()
            if not '.' in filename :
                filename = filename + '.sql'
            f = open(filename,"w")
            f.write(self.get_query_text())
            f.close()
            self.original_text = self.get_query_text()
            self.set_filename(dialog.get_filename())
            self.is_new_file = False
        dialog.destroy()                       
        self.mainprog.update_window_title()        
        self.mainprog.table_browser.refresh(self.conn,self.db)
        return response

    def get_query_text(self):
        return self.textbuffer.get_text(self.textbuffer.get_start_iter(),self.textbuffer.get_end_iter())

    def get_selected_query_text(self):
        r = self.textbuffer.get_selection_bounds()
        if r:
            return self.textbuffer.get_text(r[0],r[1])            

    def open_value_for_edit(self,widget,data=None):
        print (data)

    def run_query(self):
        curs = self.conn.cursor()
        queryt = self.get_selected_query_text()
        if not queryt:
            queryt = self.get_query_text()
        #pdb.set_trace()
        for rs in self.result_sets:
            del rs        
        #gc.collect()
        for w in self.result_win.get_children():
            self.result_win.remove(w)
        self.result_sets = []
        bits = self.db.query_split(queryt)
        msg_sent = False
        with_error = False
        for bit in bits:
            startt = time.time()
            try:
                rows_affected = curs.execute(bit)
                while True:
                    #print("OK")
                    ## pdb.set_trace()
                    colTypes = []
                    if curs.description:
                        result_set = QueryResultSet(self.mainprog.clip,None)##, self.conn)
                        result_set.read_data( curs )
                        self.result_sets.append(result_set)
                        endt = time.time()
                        self.mainprog.message("\n{0:f} : {1} rows selected ".format( (endt-startt) , result_set.row_count ))
                        msg_sent = True
                    else:
                        if rows_affected!=-1:
                            endt = time.time()
                            self.mainprog.message("\n{0:f} : {1} rows affected ".format( (endt-startt) , curs.rowcount ))
                            msg_sent = True
                    if 'nextset' not in dir(curs):
                        break
                    if not curs.nextset():
                        break
                self.conn.commit()
            except self.db.api.ProgrammingError as  detail:
                msg = detail[1]
                self.mainprog.message(str(msg))
                self.conn.commit()
                with_error = True           
            except Exception as  detail:    
                msg = str(detail)                    
                self.mainprog.message(str(msg))
                self.conn.commit()
                with_error = True
            if with_error:
                break
        curs.close()
        if not with_error and msg_sent == False:
            endt = time.time()
            self.mainprog.message("\n{0:f} : ran ok ".format(endt-startt))
        self.mainprog.update_window_title()        
        if len(self.result_sets)==1:
            self.result_sets[0].pack_into(self.result_win)
        else:
            rbox = Gtk.VBox(False,1)
            self.result_win.add_with_viewport(rbox)
            for res in self.result_sets:
                res.pack_into(rbox)
        self.result_win.show_all()
        self.mainprog.table_browser.refresh(self.conn,self.db)
                       
class TableBrowser:              
    table_pixbuf = GdkPixbuf.Pixbuf.new_from_file(icondir + "table.png")
    systable_pixbuf = GdkPixbuf.Pixbuf.new_from_file(icondir + "table.png")
    view_pixbuf = GdkPixbuf.Pixbuf.new_from_file(icondir+"view.png")
    query_pixbuf = GdkPixbuf.Pixbuf.new_from_file(icondir+"query.png")
    
    def __init__(self, treeview, filter, mainprog):
        self.treeview = treeview
        tvcol = Gtk.TreeViewColumn()
        self.treeview.append_column(tvcol)
        render_pixbuf = Gtk.CellRendererPixbuf()
        tvcol.pack_start(render_pixbuf, False, True, 0)
        tvcol.add_attribute(render_pixbuf, 'pixbuf', 0)        
        i = 1
        tvcol = Gtk.TreeViewColumn("table")
        self.treeview.append_column(tvcol)
        cell = Gtk.CellRendererText()
        tvcol.pack_start(cell,True)
        tvcol.add_attribute(cell,'text',1)
        tvcol.set_resizable(True)
        self.treeview.set_headers_visible(False)
        self.filter = filter
        self.filter.connect("changed",self.render)
        self.treeview.connect("row-activated", self.treeview_row_activated, self.treeview)
        self.mainprog = mainprog
        self.queries = {}

    def render(self, junk):
        r = re.compile(self.filter.get_text(),re.IGNORECASE)
        self.ls.clear()
        for row in self.table_data:
            if r.search(row[1]) or r.search(row[2]):
                self.ls.append(row)
      
    def refresh(self, conn, db):
        self.ls = Gtk.ListStore(GdkPixbuf.Pixbuf,str,str,str)
        self.treeview.set_model(self.ls)
        curs = conn.cursor()
        curs.execute(db.show_tables_sql)
        self.table_data = []
        r = curs.fetchone()
        while r!= None:
            v = db.show_tables_decode(r)
            if v["type"]=="view":
                pix = self.view_pixbuf
            elif v["type"]=="table":
                pix = self.table_pixbuf
            elif v["type"]=="system table":
                pix = self.table_pixbuf
            else:
                raise Exception("Error not known type " + str(type))
            self.table_data.append([pix,v["table"],v["owner"],v["type"]])
            r = curs.fetchone()
        curs.close()
        crop = len(query_dir)
        for dir,dirs,filenames in os.walk(query_dir):
            for filename in filenames:
                f = open(query_dir+"/"+filename,'r')
                r = f.read()
                f.close()
                self.table_data.append([self.query_pixbuf,dir[crop:]+filename,r,''])
                self.queries[filename] = r                        
        
        for row in self.table_data:
            self.ls.append(row)      
        self.render(None)

    def treeview_row_activated(self,treeview,path,view_column,data1=None,data2=None):
        rowno = path[0]
        row = self.ls[rowno]        
        self.newpage = self.mainprog.new_page()
        if row[0] == self.query_pixbuf:
            self.newpage.textbuffer.set_text(row[2])
            self.newpage.is_new_file = False
            self.newpage.set_filename(query_dir+"/"+row[1])
        else:
            txt = self.mainprog.db.open_table_sql(row[2],row[1])
            self.newpage.textbuffer.set_text(txt)
            self.newpage.original_text = txt
            self.newpage.set_filename("table")
        
class MainProg:        
    def __init__(self, db):
        self.last_window_title = ""
        self.db = db      
        self.ui = Gtk.Builder()
        self.ui.add_from_file(scriptdir+'query.glade')
        self.ui.signal_autoconnect({
                "do_quit": self.app_close,
                "on_quit1_activate" : self.app_close,
                "on_run_query_activate" : self.app_func("run_query"),
                "on_run_query_output_to_text1_activate" : self.app_func("run_query_to_text"),
                "on_undo_activate" : self.app_func("undo"),
                "on_redo_activate" : self.app_func("redo"),
                "on_new1_activate" : self.new_page,
                "on_open1_activate" : self.file_open_dialog,
                "on_save1_activate" : self.app_func("file_save"),
                "on_save_as1_activate" : self.app_func("file_saveas"),
                "on_cut1_activate" : self.cut,
                "on_copy1_activate" : self.copy,
                "on_paste1_activate" : self.paste 
                })
        self.window = self.ui.get_widget("window1")
        self.window.set_icon_from_file(icondir+"db.png")
        self.notebook = self.ui.get_widget("notebook1")
        self.messages = self.ui.get_widget("messages")        
        self.apps = []
        self.conn = self.db.connect()
        self.new_page()
        self.message("Connected")
        self.clip = Gtk.Clipboard()
        self.table_browser = TableBrowser(
            self.ui.get_widget("treeview_tables"),
            self.ui.get_widget("table_browser_filter"),
            self)
        self.update_window_title()

    def app_close(self,junk,junk1=None):
        copy = [app for app in self.apps]        
        for app in copy:
            #print("close tab ") + app.filename
            if app.close_tab(self,junk) == Gtk.ResponseType.CANCEL:
                
                return 1
        Gtk.main_quit()
        
    def file_open_dialog(self,junk):
        dialog = Gtk.FileChooserDialog(
            title="Open query",
            action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL,
                     Gtk.ResponseType.CANCEL,
                     Gtk.STOCK_OPEN,
                     Gtk.ResponseType.OK))
        dialog.set_size_request(300,300)
        dialog.set_default_response(Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.file_open(dialog.get_filename())
        dialog.destroy()

    def file_open(self,filename):
        if not os.path.isfile(filename):
            return
        app = self.new_page()
        f = open(filename,"r")
        app.textbuffer.set_text(f.read())
        f.close()
        app.is_new_file = False
        app.set_filename(filename)
        self.update_window_title()
        
    def message(self,msg):
        msg = msg.replace("\n"," ")
        msg2 = ""
        for i in range(0,len(msg),120):
            msg2 += "\n  " + msg[i:i+120]
        msg2 = msg2.strip()
        msg2 = "* " + msg2
        buf = self.messages.get_buffer()
        t = buf.get_text(buf.get_start_iter(),buf.get_end_iter())
        buf.set_text(t + "\n" + msg2)
        buf.place_cursor(buf.get_end_iter()) 
        self.messages.scroll_mark_onscreen(buf.get_mark("insert"))
        
    def new_page(self,junk=None):
        app = QueryW(self)
        self.apps.append(app)
        page_no = len(self.apps)-1
        self.notebook.set_current_page(page_no)
        return app

    def close_tab(self,junk=None,tab=None):
        i = self.apps.index(tab)
        self.notebook.remove_page(i)            
        self.apps.remove(tab)

    def get_current_app(self):
        pn = self.notebook.get_current_page()
        return self.apps[pn]
   
    def app_func(self,appfunc):
        def retv(somGtkSuff):
            app = self.get_current_app()
            getattr(app,appfunc)()
        return retv

    def cut(self,duff):
        app = self.get_current_app()
        app.textbuffer.cut_clipboard(self.clip,True)
        #print("cut")
    
    def copy(self,duff):
        d = self.window.get_focus_child()
        while d.get_focus_child() != None:
            d = d.get_focus_child()
        props = dir(d)
        if 'get_buffer' in props:
            d.get_buffer().copy_clipboard(self.clip)
        elif 'get_selection' in props:
            #print("Copy from source view")
            op = ""
            app = self.get_current_app()

            selected_rows = [r[0] for r in d.get_selection().get_selected_rows()[1]]

            for i in selected_rows:
                row = app.data[i]
                for col in row:
                    op += str(col) + "	"
                op += "\n"
            self.clip.set_text(op)
    
    def paste(self,duff):
        app = self.get_current_app()
        app.textbuffer.paste_clipboard(self.clip,None,True)
        
    def main(self):
        Gtk.main()
        self.conn.close()

    def update_window_title(self):        
        dbname = self.get_one(self.db.select_db_name_sql())
        if dbname != self.last_window_title:
            self.last_window_title = dbname
            self.table_browser.refresh(self.conn,self.db)
        self.window.set_title(dbname)

    def get_one(self,sql):
        curs = self.conn.cursor()
        curs.execute(sql)
        r = curs.fetchone()
        curs.close()
        return r[0]
    
if __name__=="__main__":
    import sys
    connSetup = ConnSetup()
    db = connSetup.main()
    if not db:
        exit()
    m = MainProg(db)
    if len(sys.argv)==2:
        m.file_open(sys.argv[1]) 
    m.main()
   
