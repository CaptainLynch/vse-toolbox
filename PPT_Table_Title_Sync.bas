Option Explicit

Private Const TAG_TEMPLATE As String = "AC_SYNC_TEMPLATE"
Private Const TAG_TEMPLATE_VALUE As String = "YES"
Private Const TAG_ROLE As String = "AC_TABLE_ROLE"
Private Const TAG_ROLE_VALUE As String = "MAIN_SYNC_TABLE"

Private Const TAG_TITLE_TEMPLATE As String = "AC_TITLE_TEMPLATE"
Private Const TAG_TITLE_TEMPLATE_VALUE As String = "YES"
Private Const TAG_TITLE_ROLE As String = "AC_TITLE_ROLE"
Private Const TAG_TITLE_ROLE_VALUE As String = "MAIN_SYNC_TITLE"

Private Const COPY_BODY_FONT_COLOR As Boolean = False
Private Const COPY_BODY_FONT_STYLE As Boolean = False
Private Const MIN_HEADER_SIMILARITY As Double = 0.35
Private Const SIMILARITY_TIE_TOLERANCE As Double = 0.05

' ==========================================================
' 一、表格位置、列宽与格式同步
' 用法：
'   1. 选中范本表格，运行 SetSelectedTableAsTemplate
'   2. 缩略图窗格选中目标页，运行 SyncSelectedSlidesToTemplate
'   3. 需要时运行 ClearAllTableSyncTags 清除全部标签
' ==========================================================

Public Sub SetSelectedTableAsTemplate()
    Dim sel As Selection
    Dim shp As Shape
    Dim sld As Slide

    On Error GoTo Fail

    If Presentations.Count = 0 Or Windows.Count = 0 Then
        MsgBox "当前没有打开的演示文稿。", vbExclamation, "设置范本表格"
        Exit Sub
    End If

    Set sel = ActiveWindow.Selection

    If sel.Type = ppSelectionText Then
        MsgBox "当前只选中了单元格文字或文字光标。请按 Esc 退出文字编辑，再单击表格外框，选中整张表格后重试。", _
               vbExclamation, "设置范本表格"
        Exit Sub
    End If

    If sel.Type <> ppSelectionShapes Then
        MsgBox "请先在幻灯片编辑区选中一张 PowerPoint 原生表格。", _
               vbExclamation, "设置范本表格"
        Exit Sub
    End If

    If sel.ShapeRange.Count <> 1 Then
        MsgBox "必须且只能选中一个对象作为范本。", _
               vbExclamation, "设置范本表格"
        Exit Sub
    End If

    Set shp = sel.ShapeRange(1)

    If shp.Type = msoGroup Then
        MsgBox "所选对象是组合对象。请取消组合并单独选中 PowerPoint 原生表格后重试。", _
               vbExclamation, "设置范本表格"
        Exit Sub
    End If

    If shp.HasTable <> msoTrue Then
        MsgBox "所选对象不是 PowerPoint 原生表格。请确认选中的是整张原生表格，而不是图片、文本框或单元格文字。", _
               vbExclamation, "设置范本表格"
        Exit Sub
    End If

    Set sld = ActiveWindow.View.Slide

    ClearPreviousTemplateTags ActivePresentation

    If Not SetShapeTag(shp, TAG_TEMPLATE, TAG_TEMPLATE_VALUE) Then
        MsgBox "无法写入范本标签。对象可能被锁定或演示文稿不可编辑。", _
               vbCritical, "设置范本表格"
        Exit Sub
    End If

    MsgBox "范本表格已设置。" & vbCrLf & _
           "页码：" & CStr(sld.SlideIndex) & vbCrLf & _
           "行数：" & CStr(shp.Table.Rows.Count) & vbCrLf & _
           "列数：" & CStr(shp.Table.Columns.Count), _
           vbInformation, "设置范本表格"
    Exit Sub

Fail:
    MsgBox "设置范本表格失败：" & Err.Description, _
           vbCritical, "设置范本表格"
End Sub

Public Sub SyncSelectedSlidesToTemplate()
    Dim pres As Presentation
    Dim sel As Selection
    Dim selectedSlides As SlideRange
    Dim templateShape As Shape
    Dim templateSlide As Slide
    Dim sld As Slide
    Dim reason As String
    Dim slideReason As String
    Dim details As String
    Dim successCount As Long
    Dim templateSkipCount As Long
    Dim failureCount As Long
    Dim i As Long

    On Error GoTo FatalError

    If Presentations.Count = 0 Or Windows.Count = 0 Then
        MsgBox "当前没有打开的演示文稿。", _
               vbExclamation, "批量同步表格"
        Exit Sub
    End If

    Set pres = ActivePresentation
    Set templateShape = FindTemplateTable(pres, templateSlide, reason)

    If templateShape Is Nothing Then
        MsgBox "无法开始同步：" & reason & vbCrLf & _
               "请先选中正确表格并运行 SetSelectedTableAsTemplate。", _
               vbExclamation, "批量同步表格"
        Exit Sub
    End If

    Set sel = ActiveWindow.Selection

    If sel.Type <> ppSelectionSlides Then
        MsgBox "请先在左侧幻灯片缩略图窗格中，使用 Ctrl 或 Shift 选择要处理的页面，然后再运行此宏。", _
               vbExclamation, "批量同步表格"
        Exit Sub
    End If

    Set selectedSlides = sel.SlideRange

    If selectedSlides.Count = 0 Then
        MsgBox "没有选中任何幻灯片。", _
               vbExclamation, "批量同步表格"
        Exit Sub
    End If

    For i = 1 To selectedSlides.Count
        Set sld = selectedSlides(i)

        If sld.SlideID = templateSlide.SlideID Then
            templateSkipCount = templateSkipCount + 1
        Else
            slideReason = vbNullString

            If ProcessOneSlide(sld, templateShape, slideReason) Then
                successCount = successCount + 1
            Else
                failureCount = failureCount + 1

                If Len(details) > 0 Then
                    details = details & vbCrLf
                End If

                details = details & "第 " & CStr(sld.SlideIndex) & _
                          " 页：" & slideReason
            End If
        End If
    Next i

    MsgBox "批量同步完成。" & vbCrLf & _
           "成功处理页数：" & CStr(successCount) & vbCrLf & _
           "跳过的范本页：" & CStr(templateSkipCount) & vbCrLf & _
           "未处理页数：" & CStr(failureCount) & _
           IIf(failureCount > 0, _
               vbCrLf & "未处理明细：" & vbCrLf & details, _
               vbNullString), _
           IIf(failureCount > 0, vbExclamation, vbInformation), _
           "批量同步表格"
    Exit Sub

FatalError:
    MsgBox "批量同步未能启动或汇总结果时发生错误：" & _
           Err.Description, _
           vbCritical, "批量同步表格"
End Sub

Public Sub ClearAllTableSyncTags()
    Dim pres As Presentation
    Dim sld As Slide
    Dim removedCount As Long
    Dim failureCount As Long
    Dim reason As String
    Dim details As String

    On Error GoTo Fail

    If Presentations.Count = 0 Then
        MsgBox "当前没有打开的演示文稿。", _
               vbExclamation, "清除同步标签"
        Exit Sub
    End If

    Set pres = ActivePresentation

    For Each sld In pres.Slides
        reason = vbNullString

        If Not ClearTagsOnSlide(sld, removedCount, reason) Then
            failureCount = failureCount + 1

            If Len(details) > 0 Then
                details = details & vbCrLf
            End If

            details = details & "第 " & CStr(sld.SlideIndex) & _
                      " 页：" & reason
        End If
    Next sld

    MsgBox "标签清理完成（含表格标签与标题标签）。" & vbCrLf & _
           "已删除标签数：" & CStr(removedCount) & vbCrLf & _
           "未完成页数：" & CStr(failureCount) & _
           IIf(failureCount > 0, _
               vbCrLf & "未完成明细：" & vbCrLf & details, _
               vbNullString), _
           IIf(failureCount > 0, vbExclamation, vbInformation), _
           "清除同步标签"
    Exit Sub

Fail:
    MsgBox "清除标签时发生错误：" & Err.Description, _
           vbCritical, "清除同步标签"
End Sub

Private Function ClearTagsOnSlide( _
    ByVal sld As Slide, _
    ByRef removedCount As Long, _
    ByRef reason As String) As Boolean

    Dim shp As Shape

    On Error GoTo Fail

    For Each shp In sld.Shapes
        ClearTagsFromShape shp, removedCount
    Next shp

    ClearTagsOnSlide = True
    Exit Function

Fail:
    reason = Err.Description
End Function

Private Function ProcessOneSlide( _
    ByVal sld As Slide, _
    ByVal templateShape As Shape, _
    ByRef reason As String) As Boolean

    Dim targetShape As Shape

    On Error GoTo Fail

    Set targetShape = FindTargetTableOnSlide( _
        sld, templateShape, reason)

    If targetShape Is Nothing Then
        Exit Function
    End If

    If targetShape.Table.Columns.Count <> _
       templateShape.Table.Columns.Count Then

        reason = "目标表格列数与范本不同。"
        Exit Function
    End If

    If Not CopySafeTableFormat( _
        templateShape, targetShape, reason) Then

        Exit Function
    End If

    ProcessOneSlide = True
    Exit Function

Fail:
    reason = "处理页面时发生错误：" & Err.Description
End Function

Private Function FindTemplateTable( _
    ByVal pres As Presentation, _
    ByRef templateSlide As Slide, _
    ByRef reason As String) As Shape

    Dim sld As Slide
    Dim tables As Collection
    Dim groupedFlags As Collection
    Dim scanError As String
    Dim shp As Shape
    Dim foundShape As Shape
    Dim foundSlide As Slide
    Dim foundGrouped As Boolean
    Dim countFound As Long
    Dim i As Long

    On Error GoTo Fail

    For Each sld In pres.Slides
        scanError = vbNullString
        Set groupedFlags = New Collection

        Set tables = GetTablesOnSlide( _
            sld, groupedFlags, scanError)

        If Len(scanError) > 0 Then
            reason = "扫描第 " & CStr(sld.SlideIndex) & _
                     " 页时失败：" & scanError
            Exit Function
        End If

        For i = 1 To tables.Count
            Set shp = tables(i)

            If StrComp( _
                GetShapeTag(shp, TAG_TEMPLATE), _
                TAG_TEMPLATE_VALUE, _
                vbTextCompare) = 0 Then

                countFound = countFound + 1
                Set foundShape = shp
                Set foundSlide = sld
                foundGrouped = CBool(groupedFlags(i))
            End If
        Next i
    Next sld

    If countFound = 0 Then
        reason = "没有找到带有 " & TAG_TEMPLATE & "=" & _
                 TAG_TEMPLATE_VALUE & " 标签的范本表格。"

    ElseIf countFound > 1 Then
        reason = "存在多个隐藏范本标签。请运行 ClearAllTableSyncTags 后重新设置范本。"

    ElseIf foundGrouped Then
        reason = "范本表格位于组合对象内部，无法安全修改或定位。请取消组合后重新设置范本。"

    Else
        Set FindTemplateTable = foundShape
        Set templateSlide = foundSlide
    End If

    Exit Function

Fail:
    reason = "查找范本表格时发生错误：" & Err.Description
End Function

Private Function FindTargetTableOnSlide( _
    ByVal sld As Slide, _
    ByVal templateShape As Shape, _
    ByRef reason As String) As Shape

    Dim tables As Collection
    Dim groupedFlags As Collection
    Dim candidates As New Collection
    Dim candidateGrouped As New Collection
    Dim scanError As String
    Dim shp As Shape
    Dim taggedShape As Shape
    Dim taggedGrouped As Boolean
    Dim taggedCount As Long
    Dim templateCols As Long
    Dim i As Long
    Dim score As Double
    Dim bestScore As Double
    Dim secondScore As Double
    Dim bestIndex As Long

    On Error GoTo Fail

    templateCols = templateShape.Table.Columns.Count
    Set groupedFlags = New Collection

    Set tables = GetTablesOnSlide( _
        sld, groupedFlags, scanError)

    If Len(scanError) > 0 Then
        reason = "扫描页面中的组合对象或表格时失败：" & scanError
        Exit Function
    End If

    If tables.Count = 0 Then
        reason = "页面中没有 PowerPoint 原生表格。"
        Exit Function
    End If

    ' First priority: role-tagged table.
    For i = 1 To tables.Count
        Set shp = tables(i)

        If StrComp( _
            GetShapeTag(shp, TAG_ROLE), _
            TAG_ROLE_VALUE, _
            vbTextCompare) = 0 Then

            taggedCount = taggedCount + 1
            Set taggedShape = shp
            taggedGrouped = CBool(groupedFlags(i))
        End If
    Next i

    If taggedCount > 1 Then
        reason = "存在多个隐藏目标表格角色标签，无法确定唯一目标。"
        Exit Function

    ElseIf taggedCount = 1 Then
        If taggedGrouped Then
            reason = "带角色标签的表格位于组合对象内部，无法安全修改。"
            Exit Function
        End If

        If taggedShape.Table.Columns.Count <> templateCols Then
            reason = "带角色标签的目标表格列数与范本不同。"
            Exit Function
        End If

        Set FindTargetTableOnSlide = taggedShape
        Exit Function
    End If

    ' Second priority: tables with the same number of columns.
    For i = 1 To tables.Count
        Set shp = tables(i)

        If shp.Table.Columns.Count = templateCols Then
            candidates.Add shp
            candidateGrouped.Add CBool(groupedFlags(i))
        End If
    Next i

    If candidates.Count = 0 Then
        reason = "没有找到与范本列数相同的表格。"
        Exit Function
    End If

    If candidates.Count = 1 Then
        bestIndex = 1
    Else
        bestScore = -1#
        secondScore = -1#

        For i = 1 To candidates.Count
            Set shp = candidates(i)

            score = GetHeaderSimilarityScore( _
                templateShape, shp)

            If score > bestScore Then
                secondScore = bestScore
                bestScore = score
                bestIndex = i
            ElseIf score > secondScore Then
                secondScore = score
            End If
        Next i

        If bestScore < MIN_HEADER_SIMILARITY Then
            reason = "存在多张列数相同的候选表格，但表头相似度过低，无法安全区分。"
            Exit Function
        End If

        If Abs(bestScore - secondScore) <= _
           SIMILARITY_TIE_TOLERANCE Then

            reason = "存在多张无法区分的候选表格，最高表头相似度过于接近。"
            Exit Function
        End If
    End If

    If CBool(candidateGrouped(bestIndex)) Then
        reason = "匹配到的表格位于组合对象内部，无法安全修改。"
        Exit Function
    End If

    Set shp = candidates(bestIndex)

    If Not SetShapeTag( _
        shp, TAG_ROLE, TAG_ROLE_VALUE) Then

        reason = "已识别目标表格，但无法写入角色标签；对象可能被锁定。"
        Exit Function
    End If

    Set FindTargetTableOnSlide = shp
    Exit Function

Fail:
    reason = "定位目标表格时发生错误：" & Err.Description
End Function

Private Function GetTablesOnSlide( _
    ByVal sld As Slide, _
    ByRef groupedFlags As Collection, _
    ByRef reason As String) As Collection

    Dim result As New Collection
    Dim shp As Shape

    On Error GoTo Fail

    For Each shp In sld.Shapes
        CollectTablesFromShape _
            shp, result, groupedFlags, False, reason

        If Len(reason) > 0 Then
            Exit For
        End If
    Next shp

    Set GetTablesOnSlide = result
    Exit Function

Fail:
    reason = Err.Description
    Set GetTablesOnSlide = result
End Function

Private Sub CollectTablesFromShape( _
    ByVal shp As Shape, _
    ByRef tables As Collection, _
    ByRef groupedFlags As Collection, _
    ByVal isInsideGroup As Boolean, _
    ByRef reason As String)

    Dim i As Long
    Dim child As Shape

    On Error GoTo Fail

    If shp.Type = msoGroup Then
        For i = 1 To shp.GroupItems.Count
            Set child = shp.GroupItems(i)

            CollectTablesFromShape _
                child, _
                tables, _
                groupedFlags, _
                True, _
                reason

            If Len(reason) > 0 Then
                Exit Sub
            End If
        Next i

    ElseIf shp.HasTable = msoTrue Then
        tables.Add shp
        groupedFlags.Add isInsideGroup
    End If

    Exit Sub

Fail:
    reason = "对象""" & shp.Name & _
             """无法安全读取：" & Err.Description
End Sub

Private Function GetHeaderSimilarityScore( _
    ByVal templateShape As Shape, _
    ByVal candidateShape As Shape) As Double

    Dim colCount As Long
    Dim i As Long
    Dim sourceText As String
    Dim targetText As String
    Dim totalScore As Double
    Dim comparedCount As Long

    On Error GoTo Fail

    If templateShape.Table.Columns.Count <> _
       candidateShape.Table.Columns.Count Then

        Exit Function
    End If

    colCount = templateShape.Table.Columns.Count

    For i = 1 To colCount
        sourceText = NormalizeText( _
            GetCellTextSafe( _
                templateShape.Table.Cell(1, i)))

        targetText = NormalizeText( _
            GetCellTextSafe( _
                candidateShape.Table.Cell(1, i)))

        If Len(sourceText) > 0 Or Len(targetText) > 0 Then
            totalScore = totalScore + _
                         GetTextSimilarity(sourceText, targetText)

            comparedCount = comparedCount + 1
        End If
    Next i

    If comparedCount > 0 Then
        GetHeaderSimilarityScore = _
            totalScore / CDbl(comparedCount)
    End If

    Exit Function

Fail:
    GetHeaderSimilarityScore = 0#
End Function

Private Function GetTextSimilarity( _
    ByVal textA As String, _
    ByVal textB As String) As Double

    Dim lenA As Long
    Dim lengthb As Long
    Dim distance As Long
    Dim maxLen As Long

    lenA = Len(textA)
    lengthb = Len(textB)

    If lenA = 0 And lengthb = 0 Then
        GetTextSimilarity = 1#
        Exit Function
    End If

    If lenA = 0 Or lengthb = 0 Then
        Exit Function
    End If

    If StrComp(textA, textB, vbTextCompare) = 0 Then
        GetTextSimilarity = 1#
        Exit Function
    End If

    If InStr(1, textA, textB, vbTextCompare) > 0 Or _
       InStr(1, textB, textA, vbTextCompare) > 0 Then

        GetTextSimilarity = 0.75
        Exit Function
    End If

    distance = LevenshteinDistance(textA, textB)

    If lenA > lengthb Then
        maxLen = lenA
    Else
        maxLen = lengthb
    End If

    GetTextSimilarity = _
        1# - (CDbl(distance) / CDbl(maxLen))
End Function

Private Function LevenshteinDistance( _
    ByVal textA As String, _
    ByVal textB As String) As Long

    Dim previousRow() As Long
    Dim currentRow() As Long
    Dim i As Long
    Dim j As Long
    Dim cost As Long

    ReDim previousRow(0 To Len(textB))
    ReDim currentRow(0 To Len(textB))

    For j = 0 To Len(textB)
        previousRow(j) = j
    Next j

    For i = 1 To Len(textA)
        currentRow(0) = i

        For j = 1 To Len(textB)
            If StrComp( _
                Mid$(textA, i, 1), _
                Mid$(textB, j, 1), _
                vbTextCompare) = 0 Then

                cost = 0
            Else
                cost = 1
            End If

            currentRow(j) = MinLong( _
                currentRow(j - 1) + 1, _
                previousRow(j) + 1, _
                previousRow(j - 1) + cost)
        Next j

        For j = 0 To Len(textB)
            previousRow(j) = currentRow(j)
        Next j
    Next i

    LevenshteinDistance = previousRow(Len(textB))
End Function

Private Function MinLong( _
    ByVal valueA As Long, _
    ByVal valueB As Long, _
    ByVal valueC As Long) As Long

    MinLong = valueA

    If valueB < MinLong Then
        MinLong = valueB
    End If

    If valueC < MinLong Then
        MinLong = valueC
    End If
End Function

Private Function CopySafeTableFormat( _
    ByVal sourceShape As Shape, _
    ByVal targetShape As Shape, _
    ByRef reason As String) As Boolean

    Dim sourceTable As Table
    Dim targetTable As Table
    Dim oldWidths() As Single
    Dim oldLeft As Single
    Dim oldTop As Single
    Dim oldLockAspect As MsoTriState
    Dim geometryStored As Boolean
    Dim sourceBodyRow As Long
    Dim rowIndex As Long
    Dim colIndex As Long
    Dim colCount As Long
    Dim rollbackIndex As Long

    On Error GoTo Fail

    Set sourceTable = sourceShape.Table
    Set targetTable = targetShape.Table

    If sourceTable.Columns.Count <> _
       targetTable.Columns.Count Then

        reason = "目标表格列数与范本不同。"
        Exit Function
    End If

    colCount = sourceTable.Columns.Count
    ReDim oldWidths(1 To colCount)

    oldLeft = targetShape.Left
    oldTop = targetShape.Top
    oldLockAspect = targetShape.LockAspectRatio

    For colIndex = 1 To colCount
        oldWidths(colIndex) = _
            targetTable.Columns(colIndex).Width
    Next colIndex

    geometryStored = True

    If Not SetLockAspectRatioSafely( _
        targetShape, msoFalse) Then

        reason = "无法解除对象纵横比锁定；对象可能被锁定。"
        Exit Function
    End If

    If Not SetShapePositionSafely( _
        targetShape, sourceShape.Left, sourceShape.Top) Then

        reason = "无法设置表格位置；对象可能被锁定。"
        GoTo RollBackGeometry
    End If

    For colIndex = 1 To colCount
        If Not SetColumnWidthSafely( _
            targetShape, _
            colIndex, _
            sourceTable.Columns(colIndex).Width) Then

            reason = "无法设置第 " & CStr(colIndex) & _
                     " 列宽度；对象可能被锁定。"

            GoTo RollBackGeometry
        End If
    Next colIndex

    ' Recalibrate position after changing individual column widths.
    If Not SetShapePositionSafely( _
        targetShape, sourceShape.Left, sourceShape.Top) Then

        reason = "列宽设置后无法重新校准表格位置；对象可能被锁定。"
        GoTo RollBackGeometry
    End If

    ' Header: full font/style/color/alignment synchronization.
    For colIndex = 1 To colCount
        If Not CopyHeaderFontFormat( _
            sourceTable.Cell(1, colIndex), _
            targetTable.Cell(1, colIndex), _
            reason) Then

            reason = "表头第 " & CStr(colIndex) & _
                     " 列格式同步失败：" & reason

            GoTo RestoreLockAndFail
        End If
    Next colIndex

    ' Body: use the first non-empty template body cell per column.
    For colIndex = 1 To colCount
        sourceBodyRow = _
            GetBodySampleRow(sourceShape, colIndex)

        For rowIndex = 2 To targetTable.Rows.Count
            If Not CopyBodyFontFormat( _
                sourceTable.Cell(sourceBodyRow, colIndex), _
                targetTable.Cell(rowIndex, colIndex), _
                reason) Then

                reason = "正文第 " & CStr(rowIndex) & _
                         " 行、第 " & CStr(colIndex) & _
                         " 列格式同步失败：" & reason

                GoTo RestoreLockAndFail
            End If
        Next rowIndex
    Next colIndex

    Call SetLockAspectRatioSafely( _
        targetShape, oldLockAspect)

    CopySafeTableFormat = True
    Exit Function

RollBackGeometry:
    For rollbackIndex = 1 To colCount
        Call SetColumnWidthSafely( _
            targetShape, _
            rollbackIndex, _
            oldWidths(rollbackIndex))
    Next rollbackIndex

    Call SetShapePositionSafely( _
        targetShape, oldLeft, oldTop)

RestoreLockAndFail:
    Call SetLockAspectRatioSafely( _
        targetShape, oldLockAspect)

    Exit Function

Fail:
    reason = "复制表格格式时发生错误：" & Err.Description

    If geometryStored Then
        For rollbackIndex = 1 To colCount
            Call SetColumnWidthSafely( _
                targetShape, _
                rollbackIndex, _
                oldWidths(rollbackIndex))
        Next rollbackIndex

        Call SetShapePositionSafely( _
            targetShape, oldLeft, oldTop)

        Call SetLockAspectRatioSafely( _
            targetShape, oldLockAspect)
    End If
End Function

Private Function CopyHeaderFontFormat( _
    ByVal sourceCell As Cell, _
    ByVal targetCell As Cell, _
    ByRef reason As String) As Boolean

    Dim sourceRange As TextRange
    Dim targetRange As TextRange

    On Error GoTo Fail

    Set sourceRange = _
        sourceCell.Shape.TextFrame.TextRange

    Set targetRange = _
        targetCell.Shape.TextFrame.TextRange

    CopyFontNames sourceRange, targetRange

    targetRange.Font.Size = sourceRange.Font.Size
    targetRange.Font.Color.RGB = sourceRange.Font.Color.RGB
    targetRange.Font.Bold = sourceRange.Font.Bold
    targetRange.Font.Italic = sourceRange.Font.Italic
    targetRange.Font.Underline = sourceRange.Font.Underline

    targetRange.ParagraphFormat.Alignment = _
        sourceRange.ParagraphFormat.Alignment

    CopyHeaderFontFormat = True
    Exit Function

Fail:
    reason = Err.Description
End Function

Private Function CopyBodyFontFormat( _
    ByVal sourceCell As Cell, _
    ByVal targetCell As Cell, _
    ByRef reason As String) As Boolean

    Dim sourceRange As TextRange
    Dim targetRange As TextRange

    On Error GoTo Fail

    Set sourceRange = _
        sourceCell.Shape.TextFrame.TextRange

    Set targetRange = _
        targetCell.Shape.TextFrame.TextRange

    ' Default body behavior preserves mixed colors and styles.
    CopyFontNames sourceRange, targetRange
    targetRange.Font.Size = sourceRange.Font.Size

    targetRange.ParagraphFormat.Alignment = _
        sourceRange.ParagraphFormat.Alignment

    If COPY_BODY_FONT_COLOR Then
        targetRange.Font.Color.RGB = _
            sourceRange.Font.Color.RGB
    End If

    If COPY_BODY_FONT_STYLE Then
        targetRange.Font.Bold = sourceRange.Font.Bold
        targetRange.Font.Italic = sourceRange.Font.Italic
        targetRange.Font.Underline = sourceRange.Font.Underline
    End If

    CopyBodyFontFormat = True
    Exit Function

Fail:
    reason = Err.Description
End Function

Private Sub CopyFontNames( _
    ByVal sourceRange As TextRange, _
    ByVal targetRange As TextRange)

    targetRange.Font.Name = sourceRange.Font.Name
    targetRange.Font.NameAscii = sourceRange.Font.NameAscii
    targetRange.Font.NameFarEast = sourceRange.Font.NameFarEast
End Sub

Private Function GetBodySampleRow( _
    ByVal templateShape As Shape, _
    ByVal columnIndex As Long) As Long

    Dim rowIndex As Long
    Dim rowCount As Long

    On Error GoTo Fallback

    rowCount = templateShape.Table.Rows.Count

    If rowCount <= 1 Then
        GetBodySampleRow = 1
        Exit Function
    End If

    For rowIndex = 2 To rowCount
        If Len(NormalizeText( _
            GetCellTextSafe( _
                templateShape.Table.Cell( _
                    rowIndex, columnIndex)))) > 0 Then

            GetBodySampleRow = rowIndex
            Exit Function
        End If
    Next rowIndex

    ' The column has body rows, but all are empty.
    GetBodySampleRow = 2
    Exit Function

Fallback:
    If templateShape.Table.Rows.Count > 1 Then
        GetBodySampleRow = 2
    Else
        GetBodySampleRow = 1
    End If
End Function

Private Function SetShapePositionSafely( _
    ByVal targetShape As Shape, _
    ByVal newLeft As Single, _
    ByVal newTop As Single) As Boolean

    Dim errorNumber As Long

    On Error Resume Next

    Err.Clear
    targetShape.Left = newLeft
    errorNumber = Err.Number

    Err.Clear
    targetShape.Top = newTop

    If Err.Number <> 0 Then
        errorNumber = Err.Number
    End If

    On Error GoTo 0

    SetShapePositionSafely = (errorNumber = 0)
End Function

Private Function SetShapeSizeSafely( _
    ByVal targetShape As Shape, _
    ByVal newWidth As Single, _
    ByVal newHeight As Single) As Boolean

    Dim errorNumber As Long

    On Error Resume Next

    Err.Clear
    targetShape.Width = newWidth
    errorNumber = Err.Number

    Err.Clear
    targetShape.Height = newHeight

    If Err.Number <> 0 Then
        errorNumber = Err.Number
    End If

    On Error GoTo 0

    SetShapeSizeSafely = (errorNumber = 0)
End Function

Private Function SetColumnWidthSafely( _
    ByVal targetShape As Shape, _
    ByVal columnIndex As Long, _
    ByVal newWidth As Single) As Boolean

    Dim errorNumber As Long

    On Error Resume Next

    Err.Clear
    targetShape.Table.Columns(columnIndex).Width = newWidth
    errorNumber = Err.Number

    On Error GoTo 0

    SetColumnWidthSafely = (errorNumber = 0)
End Function

Private Function SetLockAspectRatioSafely( _
    ByVal targetShape As Shape, _
    ByVal newValue As MsoTriState) As Boolean

    Dim errorNumber As Long

    On Error Resume Next

    Err.Clear
    targetShape.LockAspectRatio = newValue
    errorNumber = Err.Number

    On Error GoTo 0

    SetLockAspectRatioSafely = (errorNumber = 0)
End Function

Private Function SetShapeTag( _
    ByVal shp As Shape, _
    ByVal tagKey As String, _
    ByVal tagValue As String) As Boolean

    Dim errorNumber As Long

    If StrComp( _
        GetShapeTag(shp, tagKey), _
        tagValue, _
        vbTextCompare) = 0 Then

        SetShapeTag = True
        Exit Function
    End If

    If Len(GetShapeTag(shp, tagKey)) > 0 Then
        If Not DeleteShapeTag(shp, tagKey) Then
            Exit Function
        End If
    End If

    On Error Resume Next

    Err.Clear
    shp.Tags.Add tagKey, tagValue
    errorNumber = Err.Number

    On Error GoTo 0

    SetShapeTag = (errorNumber = 0)
End Function

Private Function GetShapeTag( _
    ByVal shp As Shape, _
    ByVal tagKey As String) As String

    On Error Resume Next

    Err.Clear
    GetShapeTag = shp.Tags.Item(tagKey)

    On Error GoTo 0
End Function

Private Function DeleteShapeTag( _
    ByVal shp As Shape, _
    ByVal tagKey As String) As Boolean

    Dim errorNumber As Long

    If Len(GetShapeTag(shp, tagKey)) = 0 Then
        DeleteShapeTag = True
        Exit Function
    End If

    On Error Resume Next

    Err.Clear
    shp.Tags.Delete tagKey
    errorNumber = Err.Number

    On Error GoTo 0

    DeleteShapeTag = (errorNumber = 0)
End Function

Private Sub ClearPreviousTemplateTags( _
    ByVal pres As Presentation)

    Dim sld As Slide
    Dim shp As Shape

    On Error GoTo Fail

    For Each sld In pres.Slides
        For Each shp In sld.Shapes
            ClearOneTagRecursively _
                shp, TAG_TEMPLATE
        Next shp
    Next sld

    Exit Sub

Fail:
    Err.Raise _
        Err.Number, _
        "ClearPreviousTemplateTags", _
        Err.Description
End Sub

Private Sub ClearOneTagRecursively( _
    ByVal shp As Shape, _
    ByVal tagKey As String)

    Dim i As Long
    Dim child As Shape

    On Error GoTo Fail

    If Len(GetShapeTag(shp, tagKey)) > 0 Then
        If Not DeleteShapeTag(shp, tagKey) Then
            Err.Raise _
                vbObjectError + 2101, _
                "ClearOneTagRecursively", _
                "无法删除对象""" & shp.Name & """上的旧标签。"
        End If
    End If

    If shp.Type = msoGroup Then
        For i = 1 To shp.GroupItems.Count
            Set child = shp.GroupItems(i)

            ClearOneTagRecursively _
                child, tagKey
        Next i
    End If

    Exit Sub

Fail:
    Err.Raise _
        Err.Number, _
        "ClearOneTagRecursively", _
        Err.Description
End Sub

Private Sub ClearTagsFromShape( _
    ByVal shp As Shape, _
    ByRef removedCount As Long)

    Dim i As Long
    Dim child As Shape

    On Error GoTo Fail

    If Len(GetShapeTag(shp, TAG_TEMPLATE)) > 0 Then
        If Not DeleteShapeTag(shp, TAG_TEMPLATE) Then
            Err.Raise _
                vbObjectError + 2102, _
                "ClearTagsFromShape", _
                "无法删除对象""" & shp.Name & """上的范本标签。"
        End If

        removedCount = removedCount + 1
    End If

    If Len(GetShapeTag(shp, TAG_ROLE)) > 0 Then
        If Not DeleteShapeTag(shp, TAG_ROLE) Then
            Err.Raise _
                vbObjectError + 2103, _
                "ClearTagsFromShape", _
                "无法删除对象""" & shp.Name & """上的角色标签。"
        End If

        removedCount = removedCount + 1
    End If

    If Len(GetShapeTag(shp, TAG_TITLE_TEMPLATE)) > 0 Then
        If Not DeleteShapeTag(shp, TAG_TITLE_TEMPLATE) Then
            Err.Raise _
                vbObjectError + 2104, _
                "ClearTagsFromShape", _
                "无法删除对象""" & shp.Name & """上的范本标题标签。"
        End If

        removedCount = removedCount + 1
    End If

    If Len(GetShapeTag(shp, TAG_TITLE_ROLE)) > 0 Then
        If Not DeleteShapeTag(shp, TAG_TITLE_ROLE) Then
            Err.Raise _
                vbObjectError + 2105, _
                "ClearTagsFromShape", _
                "无法删除对象""" & shp.Name & """上的标题角色标签。"
        End If

        removedCount = removedCount + 1
    End If

    If shp.Type = msoGroup Then
        For i = 1 To shp.GroupItems.Count
            Set child = shp.GroupItems(i)

            ClearTagsFromShape _
                child, removedCount
        Next i
    End If

    Exit Sub

Fail:
    Err.Raise _
        Err.Number, _
        "ClearTagsFromShape", _
        Err.Description
End Sub

Private Function GetCellTextSafe( _
    ByVal tableCell As Cell) As String

    On Error Resume Next

    Err.Clear
    GetCellTextSafe = _
        tableCell.Shape.TextFrame.TextRange.Text

    On Error GoTo 0
End Function

Private Function NormalizeText( _
    ByVal value As String) As String

    Dim result As String

    result = LCase$(Trim$(value))

    result = Replace(result, vbCr, vbNullString)
    result = Replace(result, vbLf, vbNullString)
    result = Replace(result, vbTab, vbNullString)
    result = Replace(result, " ", vbNullString)
    result = Replace(result, ChrW(160), vbNullString)

    result = Replace(result, "，", vbNullString)
    result = Replace(result, ",", vbNullString)
    result = Replace(result, "。", vbNullString)
    result = Replace(result, ".", vbNullString)
    result = Replace(result, "：", vbNullString)
    result = Replace(result, ":", vbNullString)
    result = Replace(result, "；", vbNullString)
    result = Replace(result, ";", vbNullString)
    result = Replace(result, "-", vbNullString)
    result = Replace(result, "_", vbNullString)
    result = Replace(result, "（", vbNullString)
    result = Replace(result, "）", vbNullString)
    result = Replace(result, "(", vbNullString)
    result = Replace(result, ")", vbNullString)

    NormalizeText = result
End Function

' ==========================================================
' 二、标题文本框同步（完全同步 / 部分同步 两种模式）
' 用法：
'   1. 选中范本标题文本框（如"四、产品开发——"标题），运行
'      SetSelectedTextBoxAsTemplate
'   2. 缩略图窗格选中目标页，按需运行：
'      完全同步 SyncSelectedSlidesTitleFullToTemplate
'        （同步文字内容 + 字体格式 + 位置大小）
'      部分同步 SyncSelectedSlidesTitleToTemplate
'        （保留各页文字内容，只同步字体格式 + 位置大小）
'   目标标题框识别优先级：角色标签 > 与范本同名文本框 > 标题占位符
' ==========================================================

Public Sub SetSelectedTextBoxAsTemplate()
    Dim sel As Selection
    Dim shp As Shape
    Dim sld As Slide

    On Error GoTo Fail

    If Presentations.Count = 0 Or Windows.Count = 0 Then
        MsgBox "当前没有打开的演示文稿。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    Set sel = ActiveWindow.Selection

    If sel.Type = ppSelectionText Then
        MsgBox "当前只选中了文字或文字光标。请按 Esc 退出文字编辑，" & _
               "再单击文本框边框选中整个文本框后重试。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    If sel.Type <> ppSelectionShapes Then
        MsgBox "请先在幻灯片编辑区选中作为范本的标题文本框。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    If sel.ShapeRange.Count <> 1 Then
        MsgBox "必须且只能选中一个对象作为范本。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    Set shp = sel.ShapeRange(1)

    If shp.Type = msoGroup Then
        MsgBox "所选对象是组合对象。请取消组合后单独选中文本框重试。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    If shp.HasTable = msoTrue Then
        MsgBox "所选对象是表格。标题范本应选文本框；表格范本请用 SetSelectedTableAsTemplate。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    If shp.HasTextFrame <> msoTrue Then
        MsgBox "所选对象没有文字框（可能是图片或形状）。请选中标题文本框后重试。", _
               vbExclamation, "设置范本标题框"
        Exit Sub
    End If

    Set sld = shp.Parent

    ClearPreviousTitleTemplateTags ActivePresentation

    If Not SetShapeTag(shp, TAG_TITLE_TEMPLATE, TAG_TITLE_TEMPLATE_VALUE) Then
        MsgBox "无法写入范本标签。对象可能被锁定或演示文稿不可编辑。", _
               vbCritical, "设置范本标题框"
        Exit Sub
    End If

    MsgBox "范本标题框已设置。" & vbCrLf & _
           "页码：" & CStr(sld.SlideIndex) & vbCrLf & _
           "名称：" & shp.Name & vbCrLf & _
           "Left=" & CStr(shp.Left) & "  Top=" & CStr(shp.Top) & vbCrLf & _
           "Width=" & CStr(shp.Width) & "  Height=" & CStr(shp.Height), _
           vbInformation, "设置范本标题框"
    Exit Sub

Fail:
    MsgBox "设置范本标题框失败：" & Err.Description, _
           vbCritical, "设置范本标题框"
End Sub

' 完全同步：同步文字内容 + 字体格式 + 位置和大小。
Public Sub SyncSelectedSlidesTitleFullToTemplate()
    RunTitleSyncForSelectedSlides True
End Sub

' 部分同步：保留各页文字内容，只同步字体格式、位置和大小。
Public Sub SyncSelectedSlidesTitleToTemplate()
    RunTitleSyncForSelectedSlides False
End Sub

Private Sub RunTitleSyncForSelectedSlides(ByVal syncFull As Boolean)
    Dim syncName As String
    Dim pres As Presentation
    Dim sel As Selection
    Dim selectedSlides As SlideRange
    Dim templateShape As Shape
    Dim templateSlide As Slide
    Dim sld As Slide
    Dim reason As String
    Dim slideReason As String
    Dim details As String
    Dim successCount As Long
    Dim templateSkipCount As Long
    Dim failureCount As Long
    Dim i As Long

    On Error GoTo FatalError

    syncName = IIf(syncFull, "标题框完全同步", "标题框部分同步")

    If Presentations.Count = 0 Or Windows.Count = 0 Then
        MsgBox "当前没有打开的演示文稿。", _
               vbExclamation, syncName
        Exit Sub
    End If

    Set pres = ActivePresentation
    Set templateShape = FindTemplateTitle(pres, templateSlide, reason)

    If templateShape Is Nothing Then
        MsgBox "无法开始同步：" & reason & vbCrLf & _
               "请先选中文本框并运行 SetSelectedTextBoxAsTemplate。", _
               vbExclamation, syncName
        Exit Sub
    End If

    Set sel = ActiveWindow.Selection

    If sel.Type <> ppSelectionSlides Then
        MsgBox "请先在左侧幻灯片缩略图窗格中，使用 Ctrl 或 Shift 选择要处理的页面，然后再运行此宏。", _
               vbExclamation, syncName
        Exit Sub
    End If

    Set selectedSlides = sel.SlideRange

    If selectedSlides.Count = 0 Then
        MsgBox "没有选中任何幻灯片。", _
               vbExclamation, syncName
        Exit Sub
    End If

    For i = 1 To selectedSlides.Count
        Set sld = selectedSlides(i)

        If sld.SlideID = templateSlide.SlideID Then
            templateSkipCount = templateSkipCount + 1
        Else
            slideReason = vbNullString

            If ProcessOneTitleSlide(sld, templateShape, slideReason) Then
                successCount = successCount + 1
            Else
                failureCount = failureCount + 1

                If Len(details) > 0 Then
                    details = details & vbCrLf
                End If

                details = details & "第 " & CStr(sld.SlideIndex) & _
                          " 页：" & slideReason
            End If
        End If
    Next i

    MsgBox syncName & "完成。" & vbCrLf & _
           "成功处理页数：" & CStr(successCount) & vbCrLf & _
           "跳过的范本页：" & CStr(templateSkipCount) & vbCrLf & _
           "未处理页数：" & CStr(failureCount) & _
           IIf(failureCount > 0, _
               vbCrLf & "未处理明细：" & vbCrLf & details, _
               vbNullString), _
           IIf(failureCount > 0, vbExclamation, vbInformation), _
           syncName
    Exit Sub

FatalError:
    MsgBox syncName & "未能启动或汇总结果时发生错误：" & _
           Err.Description, _
           vbCritical, syncName
End Sub

Private Function FindTemplateTitle( _
    ByVal pres As Presentation, _
    ByRef templateSlide As Slide, _
    ByRef reason As String) As Shape

    Dim sld As Slide
    Dim boxes As Collection
    Dim groupedFlags As Collection
    Dim scanError As String
    Dim shp As Shape
    Dim foundShape As Shape
    Dim foundSlide As Slide
    Dim foundGrouped As Boolean
    Dim countFound As Long
    Dim i As Long

    On Error GoTo Fail

    For Each sld In pres.Slides
        scanError = vbNullString
        Set groupedFlags = New Collection

        Set boxes = GetTextBoxesOnSlide( _
            sld, groupedFlags, scanError)

        If Len(scanError) > 0 Then
            reason = "扫描第 " & CStr(sld.SlideIndex) & _
                     " 页时失败：" & scanError
            Exit Function
        End If

        For i = 1 To boxes.Count
            Set shp = boxes(i)

            If StrComp( _
                GetShapeTag(shp, TAG_TITLE_TEMPLATE), _
                TAG_TITLE_TEMPLATE_VALUE, _
                vbTextCompare) = 0 Then

                countFound = countFound + 1
                Set foundShape = shp
                Set foundSlide = sld
                foundGrouped = CBool(groupedFlags(i))
            End If
        Next i
    Next sld

    If countFound = 0 Then
        reason = "没有找到带有 " & TAG_TITLE_TEMPLATE & "=" & _
                 TAG_TITLE_TEMPLATE_VALUE & " 标签的范本标题框。"

    ElseIf countFound > 1 Then
        reason = "存在多个范本标题标签。请运行 ClearAllTableSyncTags 后重新设置。"

    ElseIf foundGrouped Then
        reason = "范本标题框位于组合对象内部，无法安全读取。请取消组合后重新设置。"

    Else
        Set FindTemplateTitle = foundShape
        Set templateSlide = foundSlide
    End If

    Exit Function

Fail:
    reason = "查找范本标题框时发生错误：" & Err.Description
End Function

Private Function ProcessOneTitleSlide( _
    ByVal sld As Slide, _
    ByVal templateShape As Shape, _
    ByVal syncFull As Boolean, _
    ByRef reason As String) As Boolean

    Dim targetShape As Shape

    On Error GoTo Fail

    Set targetShape = FindTargetTitleOnSlide( _
        sld, templateShape, reason)

    If targetShape Is Nothing Then
        Exit Function
    End If

    If Not CopyTitleGeometry( _
        templateShape, targetShape, reason) Then

        Exit Function
    End If

    If syncFull Then
        If Not CopyTitleContent( _
            templateShape, targetShape, reason) Then

            Exit Function
        End If
    End If

    If Not CopyTitleFontFormat( _
        templateShape, targetShape, reason) Then

        Exit Function
    End If

    ProcessOneTitleSlide = True
    Exit Function

Fail:
    reason = "处理页面时发生错误：" & Err.Description
End Function

Private Function CopyTitleContent( _
    ByVal sourceShape As Shape, _
    ByVal targetShape As Shape, _
    ByRef reason As String) As Boolean

    Dim sourceText As String

    On Error GoTo Fail

    sourceText = vbNullString

    If sourceShape.TextFrame.HasText = msoTrue Then
        sourceText = sourceShape.TextFrame.TextRange.Text
    End If

    targetShape.TextFrame.TextRange.Text = sourceText

    CopyTitleContent = True
    Exit Function

Fail:
    reason = "复制标题文字内容时发生错误：" & Err.Description
End Function

Private Function CopyTitleFontFormat( _
    ByVal sourceShape As Shape, _
    ByVal targetShape As Shape, _
    ByRef reason As String) As Boolean

    Dim sourceRange As TextRange
    Dim targetRange As TextRange

    On Error GoTo Fail

    If sourceShape.TextFrame.HasText <> msoTrue Then
        CopyTitleFontFormat = True
        Exit Function
    End If

    If targetShape.TextFrame.HasText <> msoTrue Then
        CopyTitleFontFormat = True
        Exit Function
    End If

    Set sourceRange = sourceShape.TextFrame.TextRange
    Set targetRange = targetShape.TextFrame.TextRange

    CopyFontNames sourceRange, targetRange

    targetRange.Font.Size = sourceRange.Font.Size
    targetRange.Font.Color.RGB = sourceRange.Font.Color.RGB
    targetRange.Font.Bold = sourceRange.Font.Bold
    targetRange.Font.Italic = sourceRange.Font.Italic
    targetRange.Font.Underline = sourceRange.Font.Underline

    targetRange.ParagraphFormat.Alignment = _
        sourceRange.ParagraphFormat.Alignment

    CopyTitleFontFormat = True
    Exit Function

Fail:
    reason = "同步标题字体格式时发生错误：" & Err.Description
End Function

Private Function FindTargetTitleOnSlide( _
    ByVal sld As Slide, _
    ByVal templateShape As Shape, _
    ByRef reason As String) As Shape

    Dim boxes As Collection
    Dim groupedFlags As Collection
    Dim scanError As String
    Dim shp As Shape
    Dim taggedShape As Shape
    Dim taggedGrouped As Boolean
    Dim taggedCount As Long
    Dim nameShape As Shape
    Dim nameGrouped As Boolean
    Dim nameCount As Long
    Dim titleShape As Shape
    Dim i As Long

    On Error GoTo Fail

    Set groupedFlags = New Collection

    Set boxes = GetTextBoxesOnSlide( _
        sld, groupedFlags, scanError)

    If Len(scanError) > 0 Then
        reason = "扫描页面中的组合对象或文本框时失败：" & scanError
        Exit Function
    End If

    If boxes.Count = 0 Then
        reason = "页面中没有带文字框的形状。"
        Exit Function
    End If

    ' First priority: role-tagged title shape.
    For i = 1 To boxes.Count
        Set shp = boxes(i)

        If StrComp( _
            GetShapeTag(shp, TAG_TITLE_ROLE), _
            TAG_TITLE_ROLE_VALUE, _
            vbTextCompare) = 0 Then

            taggedCount = taggedCount + 1
            Set taggedShape = shp
            taggedGrouped = CBool(groupedFlags(i))
        ElseIf StrComp( _
            shp.Name, _
            templateShape.Name, _
            vbTextCompare) = 0 Then

            nameCount = nameCount + 1
            Set nameShape = shp
            nameGrouped = CBool(groupedFlags(i))
        End If
    Next i

    If taggedCount > 1 Then
        reason = "存在多个标题角色标签，无法确定唯一目标。"
        Exit Function

    ElseIf taggedCount = 1 Then
        If taggedGrouped Then
            reason = "带角色标签的标题框位于组合对象内部，无法安全修改。"
            Exit Function
        End If

        Set FindTargetTitleOnSlide = taggedShape
        Exit Function
    End If

    ' Second priority: shape with the same name as the template.
    If nameCount = 1 Then
        If nameGrouped Then
            reason = "与范本同名的标题框位于组合对象内部，无法安全修改。"
            Exit Function
        End If

        If Not SetShapeTag( _
            nameShape, TAG_TITLE_ROLE, TAG_TITLE_ROLE_VALUE) Then

            reason = "已识别同名标题框，但无法写入角色标签；对象可能被锁定。"
            Exit Function
        End If

        Set FindTargetTitleOnSlide = nameShape
        Exit Function

    ElseIf nameCount > 1 Then
        reason = "页面上存在多个与范本同名的文本框，无法确定唯一目标。"
        Exit Function
    End If

    ' Third priority: slide title placeholder.
    On Error Resume Next
    Set titleShape = sld.Shapes.Title
    On Error GoTo 0

    If titleShape Is Nothing Then
        reason = "未找到标题框（无角色标签、无同名文本框，也没有标题占位符）。"
        Exit Function
    End If

    If Not SetShapeTag( _
        titleShape, TAG_TITLE_ROLE, TAG_TITLE_ROLE_VALUE) Then

        reason = "已识别标题占位符，但无法写入角色标签；对象可能被锁定。"
        Exit Function
    End If

    Set FindTargetTitleOnSlide = titleShape
    Exit Function

Fail:
    reason = "定位标题框时发生错误：" & Err.Description
End Function

Private Function GetTextBoxesOnSlide( _
    ByVal sld As Slide, _
    ByRef groupedFlags As Collection, _
    ByRef reason As String) As Collection

    Dim result As New Collection
    Dim shp As Shape

    On Error GoTo Fail

    For Each shp In sld.Shapes
        CollectTextBoxesFromShape _
            shp, result, groupedFlags, False, reason

        If Len(reason) > 0 Then
            Exit For
        End If
    Next shp

    Set GetTextBoxesOnSlide = result
    Exit Function

Fail:
    reason = Err.Description
    Set GetTextBoxesOnSlide = result
End Function

Private Sub CollectTextBoxesFromShape( _
    ByVal shp As Shape, _
    ByRef boxes As Collection, _
    ByRef groupedFlags As Collection, _
    ByVal isInsideGroup As Boolean, _
    ByRef reason As String)

    Dim i As Long
    Dim child As Shape

    On Error GoTo Fail

    If shp.Type = msoGroup Then
        For i = 1 To shp.GroupItems.Count
            Set child = shp.GroupItems(i)

            CollectTextBoxesFromShape _
                child, _
                boxes, _
                groupedFlags, _
                True, _
                reason

            If Len(reason) > 0 Then
                Exit Sub
            End If
        Next i

    ElseIf shp.HasTextFrame = msoTrue Then
        boxes.Add shp
        groupedFlags.Add isInsideGroup
    End If

    Exit Sub

Fail:
    reason = "对象""" & shp.Name & _
             """无法安全读取：" & Err.Description
End Sub

Private Function CopyTitleGeometry( _
    ByVal sourceShape As Shape, _
    ByVal targetShape As Shape, _
    ByRef reason As String) As Boolean

    Dim oldLeft As Single
    Dim oldTop As Single
    Dim oldWidth As Single
    Dim oldHeight As Single
    Dim oldLockAspect As MsoTriState

    On Error GoTo Fail

    oldLeft = targetShape.Left
    oldTop = targetShape.Top
    oldWidth = targetShape.Width
    oldHeight = targetShape.Height
    oldLockAspect = targetShape.LockAspectRatio

    If Not SetLockAspectRatioSafely( _
        targetShape, msoFalse) Then

        reason = "无法解除对象纵横比锁定；对象可能被锁定。"
        Exit Function
    End If

    If Not SetShapeSizeSafely( _
        targetShape, _
        sourceShape.Width, _
        sourceShape.Height) Then

        reason = "无法设置标题框大小；对象可能被锁定。"
        Call RestoreTitleGeometry( _
            targetShape, oldLeft, oldTop, _
            oldWidth, oldHeight, oldLockAspect)
        Exit Function
    End If

    If Not SetShapePositionSafely( _
        targetShape, _
        sourceShape.Left, _
        sourceShape.Top) Then

        reason = "无法设置标题框位置；对象可能被锁定。"
        Call RestoreTitleGeometry( _
            targetShape, oldLeft, oldTop, _
            oldWidth, oldHeight, oldLockAspect)
        Exit Function
    End If

    Call SetLockAspectRatioSafely( _
        targetShape, oldLockAspect)

    CopyTitleGeometry = True
    Exit Function

Fail:
    reason = "复制标题框位置大小时发生错误：" & Err.Description

    Call RestoreTitleGeometry( _
        targetShape, oldLeft, oldTop, _
        oldWidth, oldHeight, oldLockAspect)
End Function

Private Function RestoreTitleGeometry( _
    ByVal targetShape As Shape, _
    ByVal oldLeft As Single, _
    ByVal oldTop As Single, _
    ByVal oldWidth As Single, _
    ByVal oldHeight As Single, _
    ByVal oldLockAspect As MsoTriState) As Boolean

    On Error Resume Next

    Err.Clear
    Call SetShapeSizeSafely(targetShape, oldWidth, oldHeight)
    Call SetShapePositionSafely(targetShape, oldLeft, oldTop)
    Call SetLockAspectRatioSafely(targetShape, oldLockAspect)

    RestoreTitleGeometry = (Err.Number = 0)

    On Error GoTo 0
End Function

Private Sub ClearPreviousTitleTemplateTags( _
    ByVal pres As Presentation)

    Dim sld As Slide
    Dim shp As Shape

    On Error GoTo Fail

    For Each sld In pres.Slides
        For Each shp In sld.Shapes
            ClearOneTitleTagRecursively _
                shp, TAG_TITLE_TEMPLATE
        Next shp
    Next sld

    Exit Sub

Fail:
    Err.Raise _
        Err.Number, _
        "ClearPreviousTitleTemplateTags", _
        Err.Description
End Sub

Private Sub ClearOneTitleTagRecursively( _
    ByVal shp As Shape, _
    ByVal tagKey As String)

    Dim i As Long
    Dim child As Shape

    On Error GoTo Fail

    If Len(GetShapeTag(shp, tagKey)) > 0 Then
        If Not DeleteShapeTag(shp, tagKey) Then
            Err.Raise _
                vbObjectError + 2106, _
                "ClearOneTitleTagRecursively", _
                "无法删除对象""" & shp.Name & """上的旧标题标签。"
        End If
    End If

    If shp.Type = msoGroup Then
        For i = 1 To shp.GroupItems.Count
            Set child = shp.GroupItems(i)

            ClearOneTitleTagRecursively _
                child, tagKey
        Next i
    End If

    Exit Sub

Fail:
    Err.Raise _
        Err.Number, _
        "ClearOneTitleTagRecursively", _
        Err.Description
End Sub
