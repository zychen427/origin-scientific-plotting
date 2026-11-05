import json, queue
from unittest.mock import MagicMock
import pytest
from origin_pro_mcp.tools import project, style, analysis, graph
from origin_pro_mcp.daemon import Session

def test_project_replacement_requires_explicit_flag(monkeypatch):
    o=MagicMock(); monkeypatch.setattr(project,"get_origin",lambda:o)
    with pytest.raises(ValueError,match="replace_current"): project.new_project()
    o.NewProject.assert_not_called()

def test_legend_rejects_unintended_source_mutation():
    with pytest.raises(ValueError,match="source column"): style.set_legend("Graph1",entries="A,B")
    with pytest.raises(ValueError,match="source column"): style.apply_publication_style("Graph1",legend_entries="A,B")

def test_force_close_does_not_close_origin():
    obj=Session.__new__(Session);obj._queue=queue.Queue();obj.instance=MagicMock();obj.force_close()
    obj.instance.Exit.assert_not_called();obj.instance.Close.assert_not_called()

def test_interpolation_does_not_clear_existing(monkeypatch):
    o=MagicMock();o.CreatePage.return_value="Interp1";cmd=[]
    monkeypatch.setattr(analysis,"get_origin",lambda:o)
    monkeypatch.setattr(analysis,"require_worksheet",lambda *x:None)
    monkeypatch.setattr(analysis,"_read_column",lambda *x:[0,1])
    monkeypatch.setattr(analysis,"execute_labtalk",lambda x:cmd.append(x) or True)
    result=json.loads(analysis._interpolate_impl("Book1","Sheet1",1,2,num_points=2))
    assert result["sheet"]=="[Interp1]Sheet1"
    assert not any("wks.nrows = 0" in x for x in cmd)
    assert sum("col(1) = data" in x for x in cmd)==1

def test_export_refuses_existing_path(monkeypatch,tmp_path):
    monkeypatch.setattr(graph,"require_graph",lambda *_:None)
    monkeypatch.setattr(graph,"activate_window",lambda *_:None)
    monkeypatch.setattr(graph,"windows_path",lambda p,*_:p)
    target=tmp_path/"figure.png";target.write_bytes(b"old")
    with pytest.raises(ValueError,match="already exists"):graph._export_via_expgraph("Graph1",str(target),width=1200,format="png")
    assert target.read_bytes()==b"old"



def test_timeout_only_warns_and_blocks_queued_calls():
    from origin_pro_mcp.daemon import Daemon
    d=Daemon(); d._watchdog=MagicMock();d._dispatch_timeout=1;d._dispatch_kill_grace=1;d._clock=lambda:0;d._safe_send=MagicMock()
    session=MagicMock();session.pid=999
    d._submit_with_dispatch_timeout(session,"sid","r1","some_tool",{},object())
    calls=d._watchdog.arm.call_args_list
    assert len(calls)==1 and calls[0].args[1] is None and calls[0].kwargs["reason"]=="dispatch-warn"
    d._submit_with_dispatch_timeout(session,"sid","r2","some_tool",{},object())
    assert session.submit.call_count==1
    assert "still in progress" in d._safe_send.call_args.args[1]["error"]


@pytest.mark.parametrize("columns", ["[[1,2],[3,\"bad\"]]", "[[1,2],[3,Infinity]]", "[[1,2],[3,true]]"])
def test_worksheet_prevalidates_all_columns(monkeypatch, columns):
    from origin_pro_mcp.tools import worksheet
    o=MagicMock();monkeypatch.setattr(worksheet,"get_origin",lambda:o)
    monkeypatch.setattr(worksheet,"require_worksheet",lambda *args:"[Book1]Sheet1")
    with pytest.raises(ValueError):worksheet.set_worksheet_data("Book1","Sheet1",columns)
    o.PutWorksheet.assert_not_called()


def test_project_rejection_does_not_open_origin(monkeypatch):
    monkeypatch.setattr(project,"get_origin",lambda: pytest.fail("should not connect"))
    with pytest.raises(ValueError,match="replace_current"):project.new_project()


def test_excel_import_uses_new_workbook(monkeypatch,tmp_path):
    from origin_pro_mcp.tools import worksheet
    f=tmp_path/"data.xlsx";f.write_bytes(b"test")
    o=MagicMock();o.CreatePage.return_value="MCPExcelImport";o.LTStr.return_value="imported"
    monkeypatch.setattr(worksheet,"get_origin",lambda:o)
    monkeypatch.setattr(worksheet,"windows_path",lambda p,*_:p)
    states=iter([["Existing"],["Existing","imported"]]);monkeypatch.setattr(worksheet,"workbook_names",lambda:next(states))
    active=[];monkeypatch.setattr(worksheet,"activate_window",lambda name,*_:active.append(name))
    monkeypatch.setattr(worksheet,"execute_labtalk",lambda *_:True)
    result=json.loads(worksheet._import_excel_impl(str(f)))
    assert active==["MCPExcelImport"] and result["name"]=="imported"

def test_excel_import_aborts_name_collision_before_writing(monkeypatch,tmp_path):
    from origin_pro_mcp.tools import worksheet
    f=tmp_path/"data.xlsx";f.write_bytes(b"test");o=MagicMock()
    monkeypatch.setattr(worksheet,"get_origin",lambda:o);monkeypatch.setattr(worksheet,"windows_path",lambda p,*_:p)
    monkeypatch.setattr(worksheet,"workbook_names",lambda:["Existing"])
    with pytest.raises(ValueError,match="already exists"):worksheet._import_excel_impl(str(f),"Existing")
    o.CreatePage.assert_not_called()
