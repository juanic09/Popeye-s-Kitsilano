Option Explicit

' Popeyes Kitsilano - Callback Log automation (runs on every month tab).
'  1. DATE LOGGED fills in with today's date when someone starts a new row.
'  2. Setting STATUS to Completed moves the row to the bottom of the table.
'     Setting a completed row back to another status moves it back up
'     under the open orders.

Private Const FIRST_ROW As Long = 6
Private Const LAST_COL As Long = 12        ' column L
Private Const DATE_COL As Long = 1         ' column A
Private Const STATUS_COL As Long = 9       ' column I
Private Const DONE_STATUS As String = "Completed"
Private Const DATE_FORMAT As String = "mmm d, yyyy"

Private Sub Workbook_SheetChange(ByVal Sh As Object, ByVal Target As Range)
    If TypeName(Sh) <> "Worksheet" Then Exit Sub
    If Not IsLogSheet(Sh) Then Exit Sub

    Dim lastRow As Long
    lastRow = TableLastRow(Sh)
    If lastRow <= FIRST_ROW Then Exit Sub

    Dim changed As Range
    Set changed = Intersect(Target, Sh.Range(Sh.Cells(FIRST_ROW, 1), Sh.Cells(lastRow, LAST_COL)))
    If changed Is Nothing Then Exit Sub

    On Error GoTo CleanUp
    Application.EnableEvents = False

    StampNewRows Sh, changed
    MoveRowsByStatus Sh, changed, lastRow

CleanUp:
    Application.ScreenUpdating = True
    Application.EnableEvents = True
End Sub

' Only the callback log tabs (header row 5 has DATE LOGGED ... STATUS).
Private Function IsLogSheet(ByVal ws As Worksheet) As Boolean
    IsLogSheet = (UCase$(CellText(ws.Cells(5, DATE_COL))) = "DATE LOGGED" And _
                  UCase$(CellText(ws.Cells(5, STATUS_COL))) = "STATUS")
End Function

' The table ends at the last row that still has the Status dropdown.
Private Function TableLastRow(ByVal ws As Worksheet) As Long
    Dim r As Long
    r = FIRST_ROW - 1
    Do While r < FIRST_ROW + 1000
        If Not HasDropdown(ws.Cells(r + 1, STATUS_COL)) Then Exit Do
        r = r + 1
    Loop
    TableLastRow = r
End Function

Private Function HasDropdown(ByVal cell As Range) As Boolean
    Dim t As Long
    On Error Resume Next
    t = cell.Validation.Type
    HasDropdown = (Err.Number = 0 And t = 3)   ' 3 = xlValidateList
    On Error GoTo 0
End Function

' ---------------------------------------------------------------------------
' 1. Date Logged
' A row is new when everything filled in so far is part of this edit, so
' editing an older row never overwrites or back-fills its date.
' ---------------------------------------------------------------------------
Private Sub StampNewRows(ByVal ws As Worksheet, ByVal changed As Range)
    Dim area As Range, r As Long, entryCells As Range
    For Each area In changed.Areas
        For r = area.Row To area.Row + area.Rows.Count - 1
            If CellText(ws.Cells(r, DATE_COL)) = "" Then
                Set entryCells = ws.Range(ws.Cells(r, DATE_COL + 1), ws.Cells(r, LAST_COL))
                If RowHasEntry(entryCells) And FilledOnlyByThisEdit(entryCells, changed) Then
                    ws.Cells(r, DATE_COL).NumberFormat = DATE_FORMAT
                    ws.Cells(r, DATE_COL).Value = Date
                End If
            End If
        Next r
    Next area
End Sub

Private Function RowHasEntry(ByVal rowCells As Range) As Boolean
    Dim c As Range
    For Each c In rowCells.Cells
        If CellText(c) <> "" Then
            RowHasEntry = True
            Exit Function
        End If
    Next c
End Function

Private Function FilledOnlyByThisEdit(ByVal rowCells As Range, ByVal changed As Range) As Boolean
    Dim c As Range
    For Each c In rowCells.Cells
        If CellText(c) <> "" Then
            If Intersect(c, changed) Is Nothing Then Exit Function
        End If
    Next c
    FilledOnlyByThisEdit = True
End Function

' ---------------------------------------------------------------------------
' 2. Completed rows to the bottom
' Rows are moved whole (cut + insert) so row height, colours and notes go
' with them.
' ---------------------------------------------------------------------------
Private Sub MoveRowsByStatus(ByVal ws As Worksheet, ByVal changed As Range, ByVal lastRow As Long)
    Dim statusCells As Range
    Set statusCells = Intersect(changed, ws.Range(ws.Cells(FIRST_ROW, STATUS_COL), ws.Cells(lastRow, STATUS_COL)))
    If statusCells Is Nothing Then Exit Sub

    Dim rowNums() As Long, n As Long, c As Range
    ReDim rowNums(1 To statusCells.Cells.Count)
    For Each c In statusCells.Cells
        n = n + 1
        rowNums(n) = c.Row
    Next c
    SortAscending rowNums, n

    ' Completed rows go to the bottom, top to bottom so they keep their order.
    ' Each move shifts the rows under it up by one.
    Dim reopened() As Long, nReopened As Long, i As Long, r As Long, shifted As Long
    ReDim reopened(1 To n)
    For i = 1 To n
        r = rowNums(i) - shifted
        If IsDone(ws, r) Then
            If Not InCompletedBlock(ws, r, lastRow) Then
                MoveRow ws, r, lastRow + 1
                shifted = shifted + 1
            End If
        ElseIf CellText(ws.Cells(r, STATUS_COL)) <> "" Then
            nReopened = nReopened + 1
            reopened(nReopened) = r
        End If
    Next i

    ' Rows taken off Completed go back up into the first empty row under the
    ' open orders. Moving a row up does not shift the rows below it.
    Dim gap As Long
    For i = 1 To nReopened
        r = reopened(i)
        gap = FirstEmptyRow(ws, lastRow)
        If gap > 0 And gap < r Then MoveRow ws, r, gap
    Next i
End Sub

Private Function IsDone(ByVal ws As Worksheet, ByVal r As Long) As Boolean
    IsDone = (StrComp(CellText(ws.Cells(r, STATUS_COL)), DONE_STATUS, vbTextCompare) = 0)
End Function

' True when every row under r is already Completed (row is in place).
Private Function InCompletedBlock(ByVal ws As Worksheet, ByVal r As Long, ByVal lastRow As Long) As Boolean
    Dim below As Long
    For below = r + 1 To lastRow
        If Not IsDone(ws, below) Then Exit Function
    Next below
    InCompletedBlock = True
End Function

Private Function FirstEmptyRow(ByVal ws As Worksheet, ByVal lastRow As Long) As Long
    Dim r As Long
    For r = FIRST_ROW To lastRow
        If Not RowHasEntry(ws.Range(ws.Cells(r, 1), ws.Cells(r, LAST_COL))) Then
            FirstEmptyRow = r
            Exit Function
        End If
    Next r
End Function

' Moves row fromRow so it sits directly above beforeRow.
Private Sub MoveRow(ByVal ws As Worksheet, ByVal fromRow As Long, ByVal beforeRow As Long)
    Application.ScreenUpdating = False
    ws.Rows(fromRow).Cut
    ws.Rows(beforeRow).Insert Shift:=-4121     ' xlShiftDown
    Application.CutCopyMode = False
End Sub

Private Sub SortAscending(ByRef values() As Long, ByVal n As Long)
    Dim i As Long, j As Long, v As Long
    For i = 2 To n
        v = values(i)
        j = i - 1
        Do While j >= 1
            If values(j) <= v Then Exit Do
            values(j + 1) = values(j)
            j = j - 1
        Loop
        values(j + 1) = v
    Next i
End Sub

Private Function CellText(ByVal c As Range) As String
    If IsError(c.Value) Then Exit Function
    CellText = Trim$(CStr(c.Value))
End Function
