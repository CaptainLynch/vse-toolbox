
/** ..\styles\controls\configurableGrid.css **/
/* Configurable Grid*/
.arasExcelDataGrid.dojoxGrid .dojoxGridContent .dojoxGridCellFocus {
	padding: 0px 2px!important;
}

.arasExcelDataGrid .dojoxGridView div.dojoxGridRowSelected .dojoxGridRowTable tr .dojoxGridCell:not([bginvert="false"]), .arasExcelDataGrid .dojoxGridView div.dojoxGridRowSelected .dojoxGridRowTable tr .dojoxGridCell:not([bginvert="false"]) a, .arasExcelDataGrid .dojoxGridView div.dojoxGridRowOver tr .dojoxGridCell, .arasExcelDataGrid .dojoxGridView div.dojoxGridRowSelected tr .dojoxGridCell, .arasExcelDataGrid .dojoxGridRowSelected, .arasExcelDataGrid .dojoxGridView div.dojoxGridRowOver .dojoxGridRowTable tr .dojoxGridCell:not([bginvert="false"]), .arasExcelDataGrid .dojoxGridView div.dojoxGridRowOver .dojoxGridRowTable tr .dojoxGridCell:not([bginvert="false"]) a {
	background-color: transparent !important;
}

.arasExcelDataGrid .dojoxGridRowTable tr {
	height: 26px;
}

.arasExcelDataGrid .dojoxGridCell .dijitComboBox .dijitInputInner {
	height: 21px !important;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.arasExcelDataGrid .dijitTextArea { 
		min-height: 21px !important;
		margin-top: 3px !important;
	}

	.arasExcelDataGrid .dijitTextArea:focus::selection {
		background: #3399FF;
		color: #fff;
	}
}

/* Hack for Microsoft Edge 12+*/
@supports (-ms-ime-align:auto) {
	.arasExcelDataGrid .dijitTextArea { 
		min-height: 21px !important;
		margin-top: 3px !important;
	}

	.arasExcelDataGrid .dijitTextArea:focus::selection {
		background: #3399FF;
		color: #fff;
	}
}

.arasExcelDataGrid .cellMultilineNode, .arasExcelDataGrid .cellFirstMultilineNode {
	font: 12px/17px Tahoma, Arial, Helvetica, sans-serif;
	overflow: hidden;
	word-break: keep-all;
	word-wrap: break-word;
	white-space: pre-wrap;
}

.arasExcelDataGrid .dojoxGridCellFocus .cellFirstMultilineNode {
	margin-top: -1px;
}

.arasExcelDataGrid .dojoxGridCell .dijitTextArea {
	font: 12px/17px Tahoma, Arial, Helvetica, sans-serif;
	margin-top: -1px;
	padding: 0px !important;
	overflow-x: hidden !important;
	word-break: keep-all;
	word-wrap: break-word;
	resize: none;
}

.claro .arasExcelDataGrid .dojoxGridRowOdd .dojoxGridRowTable tr {
	background: none;
}
/* end of Configurable Grid*/
/** ..\styles\controls\grid.css **/
/* Grid */

.grid_icon_fix {
	background-image: url('../styles/controls/../../images/InfoActions.svg'),
		url('../styles/controls/../../images/InfoActionsHover.svg'),
		url('../styles/controls/../../images/checkbox-unchecked.svg'),
		url('../styles/controls/../../images/checkbox-checked.svg');
}

/* Header */
.claro .dojoxGrid {
	border-width: 0px;
}

.claro .dojoxGridSortNode {
	width: 99%;
}

.claro .dojoxGridSortNode,
.claro .dojoxGridColCaption {
	word-wrap: normal;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.claro .dojoxGridMasterHeader {
	min-height: 28px;
	filter: ; /* remove blue area presents next to the Grid Header (IR-023289) */
	border-style: none none solid solid;
}

div.dojoxGridHeader table.dojoxGridRowTable,
.claro .dojoxGridMasterHeader {
	border-collapse: collapse;
	background: none repeat scroll 0 0 #ffffff;
}

div.dojoxGridHeader table.dojoxGridRowTable tbody {
	background-color: #f6f6f6 !important;
}

.claro .dojoxGridHeader {
	border-top: 1px solid #ccc !important;
}

.claro .dojoxGridHeader .dojoxGridCell {
	position: relative;
	border-width: 0px 1px 1px 0px;
	border-color: #cccccc;
	border-style: solid;
	font-size: 13px;
	padding: 4px 3px 4px 2px !important;
	text-align: center;
}

.claro .dojoxGridContent .dojoxGridCell,
.claro .dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
	padding: 3px 2px 3px 3px !important;
	border-right: 1px solid #ccc !important;
	border-bottom: 1px solid #ccc !important;
}

/* Search bar */
tr.SearchBar td {
	background-color: #dde7f5 !important;
	border-width: 0px 1px 1px 0px !important;
	border-color: #ccc !important;
	border-style: solid !important;
	font-size: 9pt;
}

tr.SearchBar td .dijitTextBox {
	height: 22px;
	width: 100%;
}

tr.SearchBar td input {
	padding-bottom: 3px !important;
	width: 100%;
	-moz-box-sizing: border-box;
	box-sizing: border-box;
	border-color: transparent;
	margin-top: 2px;
}

tr.SearchBar td input:focus {
	box-shadow: none;
}

.SearchBar .dijitSelect .dijitInputField,
.SearchBar .dijitTextBox .dijitInputField,
.claro .dijitSelect .dijitInputField,
.claro .dijitTextBox .dijitInputField {
	padding: 0px 2px;
}

.SearchBar.dijitTextBoxFocused .dijitInputContainer,
.SearchBar .dijitTextBoxFocused,
.claro .dijitTextBoxFocused {
	background: none repeat scroll 0 0 #fff;
}

.SearchBar span.dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/arrow-blue-b.svg');
	background-position: -7px center !important;
}

.SearchBar span.dijitArrowButtonInner:hover,
.SearchBar td:first-child:hover span.dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/arrow-blue-b-hover.svg');
}

.SearchBar span.dijitButtonNode,
.claro .dojoxGridHeader .dojoxGridCellOver,
.claro .dojoxGridCellOver .dojoxGridSortNode {
	background-color: transparent !important;
}

.SearchBar .dijitValidationTextBoxError .dijitValidationContainer {
	height: 20px;
}

.SearchBar .dijitComboBox .dijitArrowButtonInner:hover {
	background-image: url('../styles/controls/../../images/dropdown-hover.svg');
}

.SearchBar .dijitComboBox .dijitArrowButtonInner,
.SearchBar .dojoxCheckedMultiSelect .dijitArrowButtonInner {
	max-height: 22px !important;
	max-width: 22px !important;
	width: 22px !important;
	height: 22px !important;
	background-size: 22px 22px;
	border: 0px none !important;
}

.SearchBar .dijitComboBoxOpenOnClickHover .dijitArrowButtonInner,
.SearchBar .dijitComboBox .dijitDownArrowButtonHover .dijitArrowButtonInner {
	background-position: 0 center;
}

.dojoxGridContent .dijitComboBox .dijitArrowButtonInner,
.dojoxGridContent .dojoxCheckedMultiSelect .dijitArrowButtonInner {
	width: 17px !important;
	height: 17px !important;
	max-height: 17px !important;
	max-width: 17px !important;
	background-size: 17px 17px;
}

.SearchBar .InputHelper .dijitComboBox .dijitArrowButtonInner {
	max-height: 22px !important;
	max-width: 22px !important;
	width: 22px !important;
	height: 22px !important;
	border: 0 none !important;
	background-position: 0px 0px;
	background-repeat: no-repeat;
}

.SearchBar .InputHelper .dijitComboBox .dijitArrowButtonInner,
.dojoxGrid .InputHelper .dijitComboBox .dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/ellipsis.svg');
}

.SearchBar .InputHelper .dijitComboBox .dijitArrowButtonInner:hover,
.dojoxGrid .InputHelper .dijitComboBox .dijitArrowButtonInner:hover {
	background-image: url('../styles/controls/../../images/ellipsis-hover.svg');
}

.SearchBar .dijitSelect .dijitArrowButtonInner {
	background-position: 0px 0px;
	background-image: url('../styles/controls/../../images/dropdown-arrow.svg');
}
/* end of Search bar */

.claro .dijitComboBox input:focus {
	box-shadow: none !important;
}

.claro .dijitTextBoxHover {
	background-position: 0px 0;
	background-image: none !important;
}

.dijitSpinner .dijitSpinnerButtonContainer,
.dijitComboBox .dijitArrowButtonContainer {
	border-width: 0px !important;
}

.claro .dojoxGridArrowButtonNode {
	background: url('../styles/controls/../../images/arrow-b.svg') no-repeat;
	padding: 0px !important;
	margin-left: 3px !important;
	height: 5px;
	width: 8px;
	float: none !important;
	display: inline-block;
}

.claro .dojoxGridSortUp .dojoxGridArrowButtonNode {
	background-position: 0px 0;
	background: url('../styles/controls/../../images/arrow-t.svg') no-repeat scroll left center
		transparent;
}

.claro .dojoxGridHeader:first-child {
	margin-left: -2px;
}

.claro .dojoxGridRowOdd .dojoxGridRowTable tr {
	background-color: #f6f6f6;
}

.claro .dojoxGridRowOver .dojoxGridCell,
.claro .dojoxGridRowSelected .dojoxGridRowTable tr {
	background: none;
	border-top: 0 none;
	background-color: #f8eec0;
}

div.dojoxGridRowOver
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false']),
div.dojoxGridRowOver
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false'])
	a,
div.dojoxGridRowSelected
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false']),
div.dojoxGridRowSelected
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false'])
	a {
	background-color: #f8eec0 !important;
}
div.dojoxGridRowOver
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false']) {
	background-color: #fcf7de !important;
}
div.dojoxGridRowOver.dojoxGridRowSelected
	.dojoxGridRowTable
	tr
	.dojoxGridCell:not([bginvert='false']) {
	background-color: #f2e3a0 !important;
}
/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	div.dojoxGridRowOver
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']),
	div.dojoxGridRowOver
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false'])
		a,
	div.dojoxGridRowSelected
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']),
	div.dojoxGridRowSelected
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']) {
		background: transparent !important;
		background-clip: padding-box !important;
		background: #F8EEC0\9 !important;
	}
	div.dojoxGridRowOver
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']),
	div.dojoxGridRowSelected
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']) {
		background-color: #f8eec0 !important;
	}
	div.dojoxGridRow.dojoxGridRowSelected table.dojoxGridRowTable {
		background-color: #f8eec0;
	}

	tr.SearchBar td:first-child {
		border-top-color: #dde7f5 !important;
	}
	div.dojoxGridRowOver
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']) {
		background-color: #fcf7de !important;
	}
	div.dojoxGridRowOver.dojoxGridRowSelected
		.dojoxGridRowTable
		tr
		.dojoxGridCell:not([bginvert='false']) {
		background-color: #f2e3a0 !important;
	}
}

.dojoxGridView {
	margin-left: -1px !important;
	top: -1px !important;
}

.dojoxGridView table td {
	font: 12px/1.4 Tahoma, Arial, Helvetica, sans-serif;
}

.dojoxGridRowTable td {
	border: 0 none !important;
}

.claro .dijitCheckBox,
.claro .dijitCheckBoxIcon {
	margin: 0 2px 0 0;
	padding: 0;
	width: 15px;
	height: 15px;
	background-size: 15px 15px !important;
}

.claro .dijitCheckBox,
.claro .dijitToggleButton .dijitCheckBoxIcon {
	background-position: 0px none;
	background: url('../styles/controls/../../images/checkbox-unchecked.svg') 0 0 no-repeat;
}

.claro .dijitCheckBoxChecked,
.claro .dijitToggleButtonChecked .dijitCheckBoxIcon {
	background-position: 0 none;
	background-image: url('../styles/controls/../../images/checkbox-checked.svg');
}

.claro .dijitCheckBoxDisabledChecked,
.claro .dijitToggleButtonDisabledChecked .dijitCheckBoxIcon {
	background-position: 0 none;
	background-image: url('../styles/controls/../../images/checkbox-disabled-checked.svg');
}

.DropDownArrowButtonInner,
.dojoxGrid .dijitComboBox .dijitArrowButtonInner {
	background: url('../styles/controls/../../images/dropdown-arrow.svg') transparent 0 center
		no-repeat;
	background-size: 22px 22px !important;
	margin: 0px !important;
	padding: 0px !important;
	max-height: 22px !important;
	max-width: 22px !important;
	padding: 0px !important;
	height: 22px !important;
	width: 22px !important;
}

.DropDownArrowButtonInner:hover,
.dojoxGrid .dijitComboBox .dijitArrowButtonInner:hover {
	background-image: url('../styles/controls/../../images/dropdown-hover.svg');
}

.dojoxGrid {
	-moz-user-select: none;
	-webkit-user-select: none;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.dijitInputInner:focus::selection {
		background: #3399ff;
		color: #fff;
	}
}

.dojoxGrid .dijitSelectFocused,
.dojoxGrid .dijitSelectFocused .dijitButtonContents,
.dojoxGrid .dijitTextBoxFocused,
.dojoxGrid .dijitTextBoxFocused .dijitButtonNode {
	border: 0px none !important;
	background-color: #fff !important;
}

.dojoxGrid .dijitSelect,
.dojoxGrid .dijitSelect .dijitButtonContents,
.dojoxGrid .dijitTextBox,
.dojoxGrid .dijitTextBox .dijitButtonNode {
	border: 0px none !important;
	background-color: transparent;
	background-image: none;
}

.dojoxGrid div.dojoxGridRowEditing .dojoxGridRowTable tr .dojoxGridCellFocus,
.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitComboBox
	.dijitInputInner:hover,
.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitComboBox:hover,
.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitTextBox:hover,
.dojoxGrid .dojoxGridContent .dijitComboBox .dijitArrowButtonInner:hover,
.dojoxGrid .dijitComboBox .dijitDownArrowButtonHover,
.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitComboBox
	.dijitInputInner:hover,
.claro .dojoxGridRowOver .dojoxGridRowEditing .dojoxGridCell {
	background-color: #fff !important;
}

.claro .dojoxGridRowEditing td {
	background-color: #fff !important;
}

.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitInputInner,
.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCell
	.dijitInputInner {
	margin-left: -2px !important;
	margin-top: 1px !important;
	margin-left: -2px \0 / IE9 !important;
	margin-top: -2px \0 / IE9 !important;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.dojoxGrid
		div.dojoxGridRowEditing
		.dojoxGridRowTable
		tr
		.dojoxGridCellFocus
		.dijitInputInner,
	.dojoxGrid
		div.dojoxGridRowEditing
		.dojoxGridRowTable
		tr
		.dojoxGridCell
		.dijitInputInner {
		margin-left: -2px !important;
	}
}

.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	.dojoxGridCellFocus
	.dijitComboBox
	.dijitInputInner {
	margin-top: 0px \0 / IE9 !important;
}

.dojoxGrid .dojoxGridContent .dojoxGridCell,
.claro .dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
	padding: 0px 2px 0px 3px !important;
	position: relative;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.dojoxGrid .dojoxGridContent .dojoxGridCell,
	.claro .dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
		padding: 1px 2px 0px 3px !important;
		padding: 0px 2px 0px 3px\9 !important;
	}
}

.dojoxGrid .redlineDeletedRow::after {
	content: '';
	position: absolute;
	left: 0px;
	right: 0px;
	top: 11px;
	height: 2px;
	background-color: #b83b1d;
}

.dojoxGrid .redlineNewRow {
	color: #2b5ea5;
}

.dojoxGrid .redlineDivLine {
	position: absolute;
	left: -2px;
	right: -2px;
	height: 2px;
	top: 50%;
	background-color: #b83b1d;
}

.dojoxGrid .redlineValueContainer {
	position: relative;
	display: inline-block;
	margin-left: 5px;
	text-align: center;
}

.dojoxGrid .checkBoxContainer {
	position: relative;
	display: inline-block;
}

.dojoxGrid .redlineValueContainer img {
	opacity: 0.6;
}

.dojoxGrid .redlineValue {
	color: #b83b1d;
	text-decoration: line-through;
}

.claro .dijitSelectHover {
	color: #3668b1 !important;
	background-color: transparent !important;
	background-image: none !important;
	border-color: #6b6b6b !important;
}

.claro .dijitSelectHover .DropDownArrowButtonInner,
.claro .dijitSelectFocused .DropDownArrowButtonInner {
	background-image: url('../styles/controls/../../images/dropdown-hover.svg') !important;
}

.claro .dijitSelectLabel {
	margin-bottom: 1px;
}

.claro .dijitSelectFocused .dijitArrowButton {
	border: medium none;
	padding: 0px;
}

.dijitSelectDisabled .DropDownArrowButtonInner,
.dijitSelectDisabled .DropDownArrowButtonInner:hover {
	background-image: url('../styles/controls/../../images/dropdown-disabled.svg') !important;
}

.dijitSelectDisabled {
	border-color: #cccccc !important;
}

.claro .dijitMenu {
	background-color: #ffffff;
	border: 1px solid #6b6b6b;
	color: #6e6e6e;
	padding: 0 0 1px;
	color: #6e6e6e;
}

.claro .dojoxGrid input[type='checkbox'].arasCheckboxOrRadio {
	display: block;
}

#search table + div.dijitContentPane {
	padding-left: 0px !important;
}

.claro .dojoxGridHeader tr:first-child .dojoxGridCell {
	border-top: 0px none;
}

.claro th.dojoxGridCellFocus {
	border-width: 0px 1px 1px 0px !important;
	border-color: #ccc !important;
	border-style: solid !important;
}

.dojoxGrid .dojoxGridContent td.dojoxGridCellFocus {
	border: 1px dashed #0000ff !important;
	padding: 2px !important;
	padding-top: 0px \0 / IE9 !important;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.dojoxGrid .dojoxGridContent td.dojoxGridCellFocus {
		padding: 2px 2px 2px 3px !important;
		padding: 2px\9 !important;
		padding-top: 0px\9 !important;
		border-left: 1.01px dashed #0000ff !important;
		border-left-width: 1px\9 !important;
		border-left-style: dashed\9 !important;
		border-left-color: #0000FF\9 !important;
	}
	.dojoxGrid .dojoxGridContent tr td.dojoxGridCellFocus:first-child {
		padding: 1px 2px !important;
	}

	.dojoxGrid .dojoxGridContent tr td.dojoxGridCellFocus:first-child:empty {
		padding: 2px !important;
	}
}

@-moz-document url-prefix() {
	.dojoxGrid .dojoxGridContent td.dojoxGridCellFocus a {
		display: inline-block;
		margin-bottom: 2px;
	}
}

.dojoxGrid div.dojoxGridRowEditing td.dojoxGridCellFocus {
	padding-bottom: 0px !important;
	padding-top: 0px !important;
}

.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	td.dojoxGridCell
	.dijitComboBox
	.dijitInputInner {
	height: 21px !important;
	margin-top: 0px !important;
	padding-bottom: 0px !important;
}

.dojoxGrid
	div.dojoxGridRowEditing
	.dojoxGridRowTable
	tr
	td.dojoxGridCell
	.dijitInputInner {
	padding-bottom: 1px !important;
	padding-top: 0px !important;
	margin-top: -1px !important;
	margin-top: 0px \0 / IE9 !important;
	margin-bottom: 1px \0 / IE9 !important;
	padding-bottom: 2px \0 / IE9 !important;
}

.dojoxGrid .dojoxGridContent .dijitComboBox .dijitArrowButtonInner {
	width: 16px !important;
	height: 16px !important;
	max-height: 16px !important;
	max-width: 16px !important;
	background-size: 16px 16px !important;
	background-position: 0px 0px;
	margin-top: 1px !important;
	margin-top: 2px \0 / IE9 !important;
	background-color: #fff !important;
}

.dojoxGrid
	.SearchBar
	.dijitDateTextBox
	.dijitDownArrowButton
	.dijitArrowButtonInner,
.dojoxGrid .InputHelperDate .dijitDownArrowButton .dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/calendar.svg');
}

.dojoxGrid
	.SearchBar
	.dijitDateTextBox
	.dijitDownArrowButton
	.dijitArrowButtonInner:hover,
.dojoxGrid
	.InputHelperDate
	.dijitDownArrowButton
	.dijitArrowButtonInner
	:hover {
	background-image: url('../styles/controls/../../images/calendar-hover.svg');
}

.dijitDateTextBox .dijitDownArrowButton:hover {
	background-color: transparent !important;
}

.hideArrowButton .dijitArrowButtonInner {
	display: none;
}

.dojoxGridView .dojoxGridContent .dojoxGridRow .dojoxGridRowTable {
	height: 26px;
}

/* Multi value list */
.claro .SearchBar .dojoxCheckedMultiSelect,
.claro .dojoxGridCell .dojoxCheckedMultiSelect {
	width: 100%;
}

.claro .dojoxCheckedMultiSelectMenuCheckBoxItemIcon {
	display: block;
}

.claro .dojoxCheckedMultiSelect tr {
	background-color: transparent !important;
}

.claro .dojoxCheckedMultiSelect .dijitArrowButton,
.claro .dojoxCheckedMultiSelect .dijitArrowButtonInner {
	margin: 0px !important;
	padding: 0px !important;
	background-position: 0px 0px !important;
}

.claro .dojoxCheckedMultiSelect .dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/dropdown-arrow.svg') !important;
}

.claro .dojoxCheckedMultiSelectHover .dijitArrowButtonInner {
	background-image: url('../styles/controls/../../images/dropdown-hover.svg') !important;
}

.claro .dojoxCheckedMultiSelectButton,
.claro .dojoxCheckedMultiSelect .dijitButtonNode,
.claro .dojoxCheckedMultiSelect .dijitButtonNode .dijitButtonContents {
	border: 0px none !important;
	background-color: transparent;
	background-image: none;
	outline: 0px !important;
}

.claro .dojoxCheckedMultiSelect .dojoxCheckedMultiSelectButton {
	width: 100%;
	table-layout: fixed;
}

.claro .dojoxCheckedMultiSelect .dijitButtonText {
	width: 99%;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.claro .dojoxCheckedMultiSelect .dijitArrowButton {
	width: 22px;
	outline: 0px !important;
}

.claro .dojoxCheckedMultiSelectMenu table {
	width: 100%;
}

.claro .dojoxCheckedMultiSelectMenu .dijitMenuItem .dijitMenuItemIcon {
	background-image: url('../styles/controls/../../images/checkbox-unchecked.svg') !important;
	background-position: 0px 0px !important;
	width: 16px !important;
	height: 16px !important;
	background-size: 16px 16px !important;
}

.claro
	.dojoxCheckedMultiSelectMenu
	.dojoxCheckedMultiSelectMenuItemChecked
	.dijitMenuItemIcon {
	background-image: url('../styles/controls/../../images/checkbox-checked.svg') !important;
}
/* end of Multi value list */

.claro .dropDownInputRow .dijitButtonNode,
.claro .safeIFrameButton .dijitButtonNode {
	height: 100%;
	padding: 0;
	background-image: none;
}

.claro .dropDownInputRow .dijitButtonNode {
	border-width: 0;
	box-shadow: none;
}

.claro .dojoxGridCell img {
	display: inline-block;
	margin-left: auto;
	margin-right: auto;
}

.claro .languageDirection_ltr .dojoxGridCell {
	direction: ltr;
}

.claro .languageDirection_rtl .dojoxGridCell {
	direction: rtl;
}

.claro td.dojoxGridCell {
	word-wrap: normal;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.gridLink {
	color: #3668b1;
	text-decoration: underline;
}

.aras_grid_checkbox {
	z-index: 1;
	width: 14px;
	height: 14px;
	margin-right: 4px;
	margin-bottom: 2px;
	vertical-align: -5px;
	display: inline-block;
	background-color: inherit;
	background-repeat: none;
	background-position: 0 0;
	background-size: 14px 14px;
}

.aras_grid_input_checkbox {
	width: 14px;
	height: 14px;
	margin-top: 2px;
	width: 13px \9;
	height: 13px \9;
	margin-top: 0px \9;
}

.aras_grid_checkbox,
.aras-dialog_search .dojoxGridCellFocus .aras_grid_checkbox {
	margin-top: 2px;
}

/* IE9 specific rule */
.dojoxGridCellFocus .aras_grid_checkbox {
	margin-top: 3px \0 / IE9;
}

.aras_grid_checkbox.checked {
	background-image: url('../styles/controls/../../images/checkbox-checked.svg');
}

.aras_grid_checkbox.unchecked {
	background-image: url('../styles/controls/../../images/checkbox-unchecked.svg');
}
/* ValidationContainer*/
.claro .dijitValidationTextBoxError .dijitValidationContainer {
	border-width: 1px;
	width: 8px;
}

.claro .dijitValidationTextBox .dijitValidationContainer {
	padding: 0px;
	background-position: 0px -1px;
}

.claro .dijitComboBox.dijitValidationTextBox .dijitValidationContainer {
	margin-top: 3px;
}

.claro .dijitComboBoxHighlightMatch {
	background-color: #f9eec0;
}

#structureTreeParent .dojoxGridView {
	top: 0px !important;
}

.dojoxGridRow {
	width: 100%;
}
.dojoxGridContent {
	overflow: visible;
}
/* end of Grid */

/* ExternalCellWidget */
.dojoxGridCell .externalWidget {
	position: absolute;
	overflow: hidden;
	top: 0px;
	left: 0px;
	right: 0px;
	bottom: 0px;
	white-space: nowrap;
	text-overflow: ellipsis;
}

.dojoxGridCell .externalExcelWidget {
	position: relative;
	display: inline-block;
	width: 100%;
	overflow: hidden;
	white-space: nowrap;
	text-overflow: ellipsis;
	vertical-align: middle;
}

.dojoxGridCellFocus .externalWidget {
	margin: -1px 0px 0px -1px;
}

.dojoxGridCellFocus .externalExcelWidget {
	margin: -1px 0px 0px 0px;
}

.externalWidget .imageButton,
.externalExcelWidget .imageButton {
	display: inline-block;
	cursor: pointer;
	width: 22px;
	height: 22px;
	max-width: 22px;
	max-height: 22px;
	vertical-align: middle;
	background-size: 22px 22px;
	background-position: 0px 0px;
	background-repeat: no-repeat;
}

.externalWidget .textLink,
.externalExcelWidget .textLink {
	cursor: pointer;
	font-size: 11px;
	color: #3668b1;
	text-decoration: underline;
}

.externalWidget.widgetDisabled .textLink,
.externalExcelWidget.widgetDisabled .textLink {
	cursor: default;
	font-size: 12px;
	color: #404040;
	text-decoration: none;
}

.externalWidget.restricted .textLink,
.externalExcelWidget.restricted .textLink {
	cursor: default;
	font-size: 12px;
	color: #ff0000;
	text-decoration: none;
	vertical-align: middle;
}

.filePropertyManager .selectButton {
	margin-left: 2px;
	background-image: url('../styles/controls/../../images/Upload.svg');
}

.filePropertyManager .selectButton:hover {
	background-image: url('../styles/controls/../../images/UploadHover.svg');
}

.filePropertyManager.widgetDisabled .selectButton {
	display: none;
}

.filePropertyManager .manageButton {
	margin-left: 2px;
	background-image: url('../styles/controls/../../images/FileProperty.svg');
}

.filePropertyManager .manageButtonUnsaved {
	margin-left: 2px;
	background-image: url('../styles/controls/../../images/FilePropertyUnsaved.svg');
}

.filePropertyManager .manageButton:hover {
	background-image: url('../styles/controls/../../images/FilePropertyHover.svg');
}

.filePropertyManager.widgetDisabled .manageButton {
	display: none;
}
/* end of ExternalCellWidget */

/** ..\styles\controls\mainTree.css **/
/* Main Tree */
.claro .dijitTreeExpandoLeaf {
	max-width: 22px;
	max-height: 10px;
}

.tundra .dijitTreeExpandoLeaf {
	display: none;
}

.dijitTreeContainer {
	overflow: auto;
	width: 100% !important;
	height: 100%;
}

.claro .dijitTreeExpando {
	background-repeat: no-repeat;
	height: 21px;
	margin-bottom: 1px;
	margin-left: 3px;
	width: 22px;
}

.dijitTreeIndent {
	width: 16px;
	padding-left:0.5px;
}

.claro .dijitTreeExpandoOpened, .claro .dijitTreeRowHover .dijitTreeExpandoOpened {
	background-image: url("../styles/controls/../../images/arrow-b.svg");
	background-position: 7px 8px;
}

.claro .dijitTreeExpandoClosed, .claro .dijitTreeRowHover .dijitTreeExpandoClosed {
	background-image: url("../styles/controls/../../images/arrow-r.svg");
	background-position: 9px 6px;
}

.claro .dijitTreeExpandoOpened, .claro .dijitTreeRowHover .dijitTreeExpandoOpened, .claro .dijitTreeExpandoClosed, .claro .dijitTreeRowHover .dijitTreeExpandoClosed {
	background-repeat: no-repeat;
	background-repeat: no-repeat;
	max-height: 21px;
	max-width: 22px;
}

.dijitTreeLabel {
	overflow: hidden !important;
	text-overflow: ellipsis !important;
	white-space: nowrap !important;
	width: inherit;
	outline: none !important;
}

.dijitTreeLabel[disabled] {
	font-style: italic;
}

#tree_contents {
	overflow: hidden !important;
	text-overflow: ellipsis !important;
	width: inherit;
}

.dijitFolderClosed, .dijitFolderOpened {
	width: 0px;
	height: 0px;
}

.dijitTree {
	overflow: visible !important;
	width: 100% !important;
}

.dijitTreeRow, .dijitTreeContent {
	text-overflow: ellipsis !important;
	white-space: nowrap !important;
	overflow: hidden !important;
	width: inherit !important;
}

.claro .dijitTreeRow {
	padding-top: 3px;
	padding-bottom: 1px;
}

.claro .dijitTreeRowHover, .claro .dijitTreeRowSelected {
	background-image: none !important;
	background-repeat: none !important;
	background-color: #dde7f5;
	border-color: #DDE7F5;
	border-width: 1px 0;
	color: #444444;
	transition-duration: 0.25s;
	cursor: default;
	padding-top: 2px;
	padding-bottom: 0px;
}

#tree .dijitTreeContent {
	margin-left: -6px;
}
/* end of Main Tree */
/** ..\styles\controls\menu.css **/
/* Menu */
.claro .dijitMenuItem, .claro .dijitTreeRow, .claro .dijitTreeNode .dojoDndItemBefore, .claro .dijitTreeNode .dojoDndItemAfter, .claro .dijitTreeRow {
	color: #444444;
}

.menu-block div {
	cursor: default !important;
}

.menu {
	margin: 0;
	padding-left: 0;
	background-color: #fff !important;
	background-image: none !important;
	white-space: nowrap;
}

.claro .menu.dijitMenuBar div.dijitMenuItem {
	padding: 5px 8px;
	height: 11px;
	margin:0;
}

.menu div span {
	font-size: 15px;
	line-height: 10px;
	vertical-align: top;
}

/* is used to hide menu (item), order is important because of same specificity with .menu > div */
div.not_displayed {
	display: none !important;
}

.menu > div:hover {
	color: #3668b1 !important;
	background-color: #fff !important;
	background-image: none !important;
	background-repeat: repeat-x;
	border: none !important;
	border-color: none !important;
}

.menu > div.dijitMenuItemSelected {
	background-color: #3668b1 !important;
	color: #fff !important;
	background-image: none !important;
	background-repeat: repeat-x;
	border: none !important;
	border-color: none !important;
}

.menu > div.dijitMenuItemSelected.dijitMenuItemDisabled, .menu > div.dijitMenuItemDisabled:hover {
	background-color: #fff !important;
	cursor: default !important;
	color: #444444 !important;
}

.claro .menu.dijitMenuBar div.dijitMenuItem.itg_viewer_menu {
	background-color: #f8eec0 !important;
	border-top: 2px solid #e78e46 !important;
	padding-top: 3px;
}

.claro .menu.dijitMenuBar div.dijitMenuItem.itg_viewer_menu:hover {
	color: #e78e46 !important;
}

.claro .menu.dijitMenuBar div.dijitMenuItem.itg_viewer_menu.dijitMenuItemSelected {
	background-color: #e78e46 !important;
	color: #fff !important;
}

.claro .dijitMenu .dijitMenuItemHover td, .claro .dijitMenu .dijitMenuItemSelected td, .claro .dijitMenuItemHover, .claro .dijitComboBoxMenu .dijitMenuItemHover, .claro .dijitMenuItemSelected {
	background-color: #dde7f5;
	background-image: none;
	background-repeat: none;
	border-color: #979797;
	position:relative;
}

.claro .dijitMenuSeparatorTop {
	border-bottom: 1px solid #979797;
}

.claro .dijitMenuExpand {
	background-image: url("../styles/controls/../../images/arrow-r.svg");
	background-position: 0px 0 !important;
	height: 8px;
	margin-bottom: 4px;
	margin-right: 3px;
	width: 8px;
}

.menu_dropdown {
	background-color: #fff;
	color: #000;
	font-size: 12px;
	box-shadow: 2px 2px 2px rgba(0, 0, 0, .5);
	border: 1px solid #979797 !important;
}

.menu_dropdown tr {
	position: relative;
	border-top: 1px solid #fff;
	margin-right: 1px;
}

.claro .dijitCheckedMenuItem .dijitMenuItemIcon, .claro .dijitRadioMenuItem .dijitMenuItemIcon, .claro .dijitMenuItemIcon.arasMenuIcon {
	height: 20px;
	width: 20px;
	max-height: 20px;
	max-width: 20px;
	background-position: 0 0;
	background-size: 20px 20px;
}

.claro .dijitMenu .dijitMenuItem td, .claro .dijitComboBoxMenu .dijitMenuItem {
	border-color: #FFFFFF;
	border-style: none;
	border-width: 0px 0;
	padding: 1px 2px 2px;
	height: 23px;
}

.claro .dijitCheckedMenuItem .dijitMenuItemIcon, .claro .dijitRadioMenuItem .dijitMenuItemIcon {
	background-image: none;
}

.claro .dijitCheckedMenuItemChecked .dijitCheckedMenuItemIcon {
	background-image: url("../styles/controls/../../images/check.svg");
}

.claro .dijitRadioMenuItemChecked .dijitCheckedMenuItemIcon {
	background-image: url("../styles/controls/../../images/RadioDot.svg");
}

.menu_doprdown tr.dijitMenuItem.dijitMenuItemDisabled td {
	padding-left: 0px;
}

.claro .dijitMenuItemDisabled .dijitMenuItemIconCell , .dijitMenuItemDisabled *, .dj_ie .dijitMenuItemDisabled *{
	color:#808080 !important;
	opacity:1;
	filter: alpha(opacity=100);
}
/* end of Menu */
/** ..\styles\controls\statusbar.css **/
/* Status bar */
#statusBar td {
	border-right: none;
}

#statusBar div {
	margin-top: 3px;
	border: none;
	cursor: default;
	float: left;
	overflow: hidden;
}

#statusBar span {
	margin: 0;
}

#statusBar #page_status img {
	display: inline;
}

.status-column {
	-moz-box-sizing: border-box;
	box-sizing: border-box;
	display: inline-block;
	display: -moz-grid;
	width: 100%;
	padding: 1px 10px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	font: 12px/1.4 Tahoma,Arial,Helvetica,sans-serif;
}

#statusBar .status-column .page-count {
	padding: 1px 10px 1px 10px;
	border: 1px solid #828282;
	border-radius: 8px;
	margin-left: 5px;
	margin-right: 5px;
}

#statusBar .status-column .page-count:hover {
	background-color: #828282;
	cursor: pointer;
}

#statusBar div:last-child {
	text-align: right;
}

#statusBar div#messages #messageCounter{
	padding: 0 3px;
}

#statusBar div#messages.hasAcknowledgeOnceMessages #messageCounter{
	background-color: #ec1010;
	border-radius: 2px;
}

#statusBar {
	width: 100%;
}

.claro #bottom {
	background-color: #515151;
	color: #fff;
}
/* end of Status bar */
/** ..\styles\controls\tabs.css **/
/* Tabs */
.claro .dijitTabContainerTop-tabs .dijitTab {
	border-radius: 0;
	font-size: 14px;
	padding: 1px 9px 3px;
	background-image: none;
	background-color: #fff;
	border: 1px solid transparent;
	box-shadow: none;
	min-width: 0px;
}

.claro .dijitTabContainerTop-tabs .dijitTabChecked , .claro .dijitTabContainerTop-tabs .dijitTab:hover {
	color: #3668b1;
}

.claro .dijitTabContainerTop-tabs .dijitTabDisabled, .claro .dijitTabContainerTop-tabs .dijitTabDisabled:hover {
	color: #444444;
	cursor: default;
	opacity: 0.5;
}
.claro .dijitTabContainerTop-tabs .dijitTabChecked {
	padding-bottom: 4px;
	border-color: #d4d4d4;
	border-bottom-color: transparent;
}

.claro .dijitSplitContainer-child, .claro .dijitBorderContainer-child {
	border: none;
}

.claro .dijitTabListContainer-top .tabStripButton {
	background: #fff;
	border: 1px solid #8a8a8a;
	cursor: default;
	font-size: 15px;
	margin-top: 1px;
	margin-right: 2px;
	padding: 0px;
	height: 24px !important;
}

#centerMiddle_relTabbar_tablist:before, #centerMiddle_relTabbar_tablist:after {
	content: "";
	position: absolute;
	left: 0;
	bottom: 0;
	height: 1px;
	width: inherit;
	border-bottom: 1px solid #B5BCC7;
}

#centerMiddle.centerMiddle__hidden {
	visibility: hidden;
}

#centerMiddle.centerMiddle__hidden #centerMiddle_relTabbar_tablist {
	visibility: hidden;
}

.relTabbar_tablist_menuBtn_border:hover, .claro .dijitTabListContainer-top .tabStripButton:hover {
	background-color: #DDE7F5;
}

.relTabbar_tablist_menuBtn {
	background-image: url("../styles/controls/../../images/arrow-b.svg") !important;
	background-position: center center !important;
}

.tabStripButton .ic-left, .tabStripButton .ic-right {
	vertical-align: 3px;
}

.tabStripButton .ic-top {
	vertical-align: 0;
}

.claro .tabStripButton .dijitButtonText {
	padding: 0;
	line-height: 1;
	text-align: center;
}

table#centerMiddle_relTabbar_menu tr { 
	position: relative;
	border-top: 1px solid #fff;
	margin-right: 1px;
}

table#centerMiddle_relTabbar_menu {
	border: 1px solid #979797 !important;
	box-shadow: 2px 2px 2px rgba(0, 0, 0, 0.5);
	color: #000000;
	display: block;
	font-size: 12px;
	left: 0;
}
.claro .tabStripButtonDisabled .dijitTabStripSlideRightIcon, .claro .dijitTabStripSlideRightIcon {
	background-image: url("../styles/controls/../../images/arrow-r.svg");
	background-position: 6px center;
	background-repeat: no-repeat;
}

.claro .tabStripButtonDisabled .dijitTabStripSlideLeftIcon, .claro .dijitTabStripSlideLeftIcon {
	background-image: url("../styles/controls/../../images/arrow-l.svg");
	background-position: 4px center;
	background-repeat: no-repeat;
}

.claro .dijitTabStripIcon {
	height: 8px;
	margin: 0 auto;
	width: 15px;
}
/* end of Tabs */
/** ..\styles\controls\toolbar.css **/
/* Toolbar */
.claro #top_toolbar.dijitContentPane {
	border-top: 1px solid #D4D4D4;
	border-bottom: 1px solid #D4D4D4;
	display: table;
	width: 100%;
	min-height: 29px;
}
.claro #top_toolbar.dijitContentPane .dijitToolbar {
	display: table-row;
	margin: 1px 0 1px 1px !important;
}

.toolbar-item {
	display: inline-block;
	text-align: center;
	margin: 1px 0 1px 1px !important;
	padding-top: 0px;
}

.claro .dijitToolbarPopup[id*="popup"] .dijitButton {
	display: block;
}
.claro .dijitToolbarPopup[id*="popup"] .dijitToolbar {
	display: block;
	border: none;
	width: auto !important;
	padding: 0 1px 1px;
}

.claro .dijitToolbarPopup[id*="popup"] .dijitToolbar .dijitButton {
	display: block;
	margin: 1px 0 0 !important;
	width: auto;
}

.claro .dijitToolbarPopup[id*="popup"] .dijitToolbar .dijitButton .dijitButtonNode {
	box-sizing: border-box;
	width: 100%;
	text-align: left;
}

.claro .dijitToolbarPopup[id*="popup"] .dijitToolbar .toolbar-separator {
	display: none;
}

.claro .dijitToolbarSeparator {
	background-image: none;
}

.claro .dijitToolbar, .claro .dijitMenuBar {
	background-color: #fff;
	padding: 0;
}

#searchbar_toolbar .dijitToolbar, #searchbar_toolbar .dijitMenuBar {
	background-color: #fff;
	padding: 1px 0px 0px;
	border-bottom: 0px none;
}

.dijitDropDownButton {
	width: auto !important;
}

.claro #top_toolbar.dijitContentPane .dijitButton[widgetId*="ssvc_discussion_button"] {
	display: table-cell;
	width: 1px;
}

.claro #top_toolbar.dijitContentPane .ssv-button-activeDisscussion.dijitButton img,
.claro #top_toolbar.dijitContentPane .ssv-button-activeDisscussion.dijitButton svg,
.claro .dijitToolbarPopup[id*="popup"] .ssv-button-activeDisscussion.dijitButton img,
.claro .dijitToolbarPopup[id*="popup"] .ssv-button-activeDisscussion.dijitButton svg {
	visibility: hidden;
}
.claro #top_toolbar.dijitContentPane .ssv-button-activeDisscussion.dijitButton .dijitIcon,
.claro .dijitToolbarPopup[id*="popup"] .ssv-button-activeDisscussion.dijitButton .dijitIcon {
	background-image: url("../styles/controls/../../images/DiscussionPanelOn.svg");
	background-size: 22px 22px;
	background-repeat: no-repeat;
}

.claro div#top_toolbar div span.toolbar-item.ssv-button-activeDisscussion span.dijitButtonNode, .claro .dijitToolbarPopup[id*="popup"] .ssv-button-activeDisscussion span.dijitButtonNode{
	padding: 2px 2px 1px !important;
	border: 1px solid #3668b1 !important;
}

.claro .dijitToolbar span.toolbar-item.ssv-button-activeDisscussion.dijitButtonFocused:not(.dijitButtonDisabled) span.dijitButtonNode {
	background: none !important;
}

.claro .dijitToolbar span.toolbar-item.ssv-button-activeDisscussion:hover:not(.dijitButtonDisabled) span.dijitButtonNode {
	background-color: #dde7f5 !important;
}

#top_mainMenu {
	/* cad_ff page */
	padding: 4px 5px 1px;
}

.toolbar {
	background-color: #fff;
	padding: 1px 0;
	white-space: nowrap;
}

.toolbar-item img {
	display: inline-block;
	max-width: 20px;
	max-height: 20px;
}

.toolbar-separator {
	display: inline-block;
	height: 22px;
	background-color: #d4d4d4 !important;
	width: 1px;
	padding: 0px;
	margin-left: 1px;
}

.claro .dijitToolbarSeparator + .dijitDropDownButton {
	margin-left: 1px;
	padding: 0;
}

.claro .dijitToolbar .dijitButtonHover .dijitButtonNode, .claro .dijitToolbar .dijitDropDownButtonHover .dijitButtonNode, .claro .dijitToolbar .dijitToggleButtonHover .dijitButtonNode, .claro .dijitToolbar .dijitComboButtonHover .dijitButtonNode, .claro .dijitToolbar .dijitButtonActive .dijitButtonNode, .claro .dijitToolbar .dijitDropDownButtonActive .dijitButtonNode, .claro .dijitToolbar .dijitToggleButtonActive .dijitButtonNode {
	background-color: #dde7f5 !important;
	background-image: none !important;
	background-repeat: no-repeat !important;
	border-width: 0px !important;
	padding: 2px;
	border-radius: 0px !important;
}

.claro .toolbar-item:hover:not(.dijitButtonDisabled) .dijitButtonNode {
	background-color: #dde7f5;
}

.claro .dijitSelectFocused {
	outline: none;
}

.claro .dijitToolbar .dijitButtonFocused .dijitButtonContents {
	outline: none !important;
}

.claro .dijitArrowButtonInner {
	background-image: url("../styles/controls/../../images/arrow-b.svg");
	background-position: 0px;
	background-repeat: no-repeat;
	max-height: 5px;
	max-width: 7px;
	margin: 8px 0 8px -1px;
	padding: 0 4px;
	height: 15px;
	width: 20px;
}

.claro .dijitToolbar .dijitToggleButtonChecked .dijitButtonNode {
	border-color: #3668b1;
	border-radius: 0px !important;
	padding: 2px 2px 1px !important;
}

.claro .dijitToolbar .dijitToggleButtonChecked .dijitButtonNode:hover {
	border: 1px solid #3668b1 !important;
}

.claro .dijitToolbar .dijitButton .dijitButtonNode, .claro .dijitToolbar .dijitDropDownButton .dijitButtonNode, .claro .dijitToolbar .dijitComboButton .dijitButtonNode, .claro .dijitToolbar .dijitToggleButton .dijitButtonNode, .claro .dijitToolbar .dijitComboBox .dijitButtonNode {
	border-radius: 0px !important;
	padding: 3px 3px 2px;
} 

.claro .dijitToolbar div.advancedTextBox {
	display: inline-block;
}

.claro .dijitToolbar div.advancedTextBox label {
	padding: 0;
}

.claro .dijitToolbar .dijitTextBox .dijitInputInner {
	padding-top: 0px !important;
}

.dijitMenuPopup .aras_toolbar_input {
	margin: 0px !important;
}

.grayImage {
	filter: url('../styles/controls/../grayscale.svg#grayscale');
	-webkit-filter: grayscale(100%);
	-webkit-opacity: 0.5;
	filter: alpha(opacity=50), gray;
	opacity:0.5;
}

.aras_toolbar_input {
	margin-left: 10px !important;
	margin-right: 10px !important;
}

div.dijitToolbarSeparator + div.advancedTextBox, div.advancedTextBox + div.dijitToolbarSeparator {
	margin-left: 7px;
}

div.grayImage > svg > g, div.grayImage > svg > path {
	 filter: url(#ToolBarGrayFilter);
}

.dijitToolbar.toolbar .dijitButtonContents {
	padding: 0px 1px;
}

.advancedTextBox input::-moz-placeholder {
	font-style: italic;
	color: #333;
}

.advancedTextBox input::-webkit-input-placeholder {
	font-style: italic;
	color: #8a8a8a;
}

.advancedTextBox input:-ms-input-placeholder {
	font-style: italic;
	color: #8a8a8a;
}

.advancedToolBarSelect {
	display: inline-block;
	margin-left: 0px !important;
	margin-right: 0px !important;
}

.advancedToolBarSelect[disabled] label {
	color: #818181;
}

.advancedToolBarSelect label {
	font-family: Tahoma, Arial, Helvetica, sans-serif;
	font-size: 12px;
	font-style: normal;
	font-variant: normal;
	font-weight: 400;
	line-height: normal;
	margin: 0px;
	padding-left: 3.6px;
	padding-right: 3.6px;
	padding-bottom: 0px;
	padding-top: 0px;
	text-align: center;
	vertical-align: middle;
	white-space: nowrap;
	color: #000000;
}

/* end of Toolbar */
/** ..\styles\controls\treeGrid.css **/
/* Tree grid */
.tundra .dijitTreeRowSelected .dijitTreeNodeContainer .aras_treegrid_row {
	background-color: transparent;
}

.tundra .dijitTreeRowHover {
	background-image: none;
}

.tundra .dijitTreeRowSelected .aras_treegrid_row, .aras_treegrid_row:hover, .tundra .dijitTreeRowSelected .dijitTreeNodeContainer .aras_treegrid_row:hover {
	background-color: #DDE7F5;
}

.tundra .dijitTreeRowSelected .dijitTreeLabel {
	background: none repeat scroll 0 0 transparent;
}

div.dojoxGridRowOver .dojoxTreeGridRowTable tr .dojoxGridCell:not([bginvert="false"]), div.dojoxGridRowOver .dojoxTreeGridRowTable tr .dojoxGridCell:not([bginvert="false"]) a, div.dojoxGridRowSelected .dojoxTreeGridRowTable tr .dojoxGridCell:not([bginvert="false"]), div.dojoxGridRowSelected .dojoxTreeGridRowTable tr .dojoxGridCell:not([bginvert="false"]) a {
	background-color: #DDE7F5 !important;
}
/* end of Tree grid */

/* Structure Browser and Classification Structure Tree grid */
.structure_tree .dijitTreeRowSelected .dijitTreeNodeContainer .aras_treegrid_row {
	background-image: none;
}

.structure_tree .aras_treegrid_row {
	padding-bottom: 3px;
	padding-top: 3px;
}

.structure_tree .aras_treegrid_row .dijitTreeExpando {
	background-position: 0px 0px;
}

.structure_tree .aras_treegrid_row div, .structure_tree .aras_treegrid_row span.dijitTreeLabel {
	display: inline-block;
}

.structure_tree .aras_treegrid_row span.dijitTreeLabel {
	height: 19px;
	vertical-align: middle;
}

.structure_tree .dijitTreeRow {
	padding-bottom: 0px;
}

.structure_tree .aras_treegrid_row .dijitTreeExpando.dijitTreeExpandoLeaf {
	display: inline-block !important;
	background-position: -7px 0;
	width: 9px;
}

.structure_tree .dijitTreeExpando {
	width: 14px;
}

.structure_tree .aras_treegrid_row > .dijitTreeExpando.dijitTreeExpandoLeaf:first-child {
	margin-left: 7px;
	width: 7px;
}
.structure_tree .dijitTreeIsLast {
	background-size: 18px 24px;
}

.structure_tree .dijitTreeRowSelected .aras_treegrid_row, .structure_tree .aras_treegrid_row:hover, .structure_tree .dijitTreeRowSelected .dijitTreeNodeContainer .aras_treegrid_row:hover {
	background-color: transparent;
	background-image: url("../styles/controls/../../imagesLegacy/treeHover.png");
}

.structure_tree .dijitTreeIsRoot div.aras_treegrid_row img.dijitTreeExpandoLeaf {
	display: none !important;
}

.structure_tree .dijitTreeIsRoot .dijitTreeNodeContainer div.aras_treegrid_row img.dijitTreeExpandoLeaf, .structure_tree .dijitTreeIsRoot div.aras_treegrid_row img.dijitTreeExpando.dijitTreeExpandoOpened + img.dijitTreeExpando.dijitTreeExpandoLeaf, .structure_tree .dijitTreeIsRoot div.aras_treegrid_row img.dijitTreeExpando.dijitTreeExpandoClosed + img.dijitTreeExpando.dijitTreeExpandoLeaf {
	display: inline-block !important;
}
/* end of Structure Browser and Classification Structure Tree grid */

/* Where Used Structure */
.where_used_structure .aras_treegrid_row {
	height: 22px;
	padding-top: 4px;
}
.tundra .where_used_structure .dijitTreeRow {
	padding-bottom: 0px;
}
/* end of Where Used Structure */

/* Aras tree */
/*BOM Structure, Impact Matrix and Project Plan Tree grid */
.claro .aras_treegrid_method_editor.dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
	border-bottom: 0px none transparent !important;
	border-right: 0px none !important;
	padding: 0 3px !important;
}

.claro .dndDragNodeContainer {
	position: absolute;
	z-index : 100;
	padding : 2px;
	border  : 1px solid #CCCCCC;
	background-color: #DDE7F5;
}

.claro .dndDragNodeContainer .dndDragAvatar {
	position: absolute;
	top     : 2px;
	bottom  : 2px;
	left    : 2px;
	width   : 60px;
	border  : 1px solid #CCCCCC;
	text-align: center;
}

.claro .dndDragNodeContainer .dndDragSource {
	position: relative;
	overflow: hidden;
	margin-left: 64px;
	border  : 1px solid #CCCCCC;
}

.claro .dndDragSource .dojoxGridCell{
	border-right: 1px solid #CCCCCC !important;
}

.claro .dndDragPlaceholder {
	height  : 2px;
	background-color: #3869B2;
}

.aras_tree td.dojoxGridCell img:last-child {
	margin-top: 3px;
}

.aras_tree td.dojoxGridCell div.dojoxGridExpando {
	margin-right: 5px;
}

.aras_tree td.dojoxGridCell .vertical_line.dojoxGridExpando {
	margin-top: 0 !important;
	min-width: 54px;
	max-width: 54px;
	min-height: 23px;
	width: auto !important;
}

.aras_tree td.dojoxGridCell .dojoxGridExpandoNode {
	background-position: 0 -1px;
	height: 16px;
	width: 14px;
}

.aras_tree .dojoxGridRowOver td.dojoxGridCell .dojoxGridExpandoNode {
	background-position: -18px -1px;
}

.aras_tree td.dojoxGridCell .dojoxGridExpandoOpened .dojoxGridExpandoNode {
	background-position: -36px -1px;
}

.aras_tree tr.dojoxGridRowCollapsed td.dojoxGridCell .vertical_line, .aras_tree tr.dojoxGridRowCollapsed td.dojoxGridCell:first-child , .aras_tree tr[dojoxtreegridpath*="/"].aras_treegrid_may_have_children td.dojoxGridCell.dojoxGridExpandoCell, .aras_tree tr.aras_treegrid_may_have_children td .vertical_line {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i.gif");
	background-position: 0px 0px;
	background-repeat: repeat-y;
}

.aras_tree tr.dojoxGridRowCollapsed td.dojoxGridCell:first-child, .aras_tree tr[dojoxtreegridpath*="/"].aras_treegrid_may_have_children td.dojoxGridCell.dojoxGridExpandoCell {
	background-position: 3px 0 !important;
}

.aras_tree tr.aras_treegrid_may_have_children td.dojoxGridCell.dojoxGridExpandoCell {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i_half.gif");
	background-position: 3px 20px !important;
	background-repeat: no-repeat;
}

.aras_tree .dojoxGridRow .dojoxGridRowTable tr:last-child td.dojoxGridCell.dojoxGridExpandoCell div.vertical_line, .aras_tree .dojoxGridRow .dojoxGridRowTable tr:last-child td.dojoxGridCell.dojoxGridExpandoCell div.vertical_line.dojoxGridExpandoOpened , .aras_tree tr.aras_treegrid_last_child_row.dojoxGridRowCollapsed td.dojoxGridCell .vertical_line, .aras_tree tr.aras_treegrid_last_child_row td.dojoxGridCell .vertical_line {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i_half.gif") !important;
	background-position: 0px 2px !important;
	background-repeat: no-repeat !important;
}

.claro .dojoxGridTreeModel .dojoxGridNoChildren .dojoxGridExpandoNode, .dj_ie6 .claro .dojoxGridTreeModel .dojoxGridNoChildren .dojoxGridExpandoNode {
	background-image: none;
	width: 7px;
}

.aras_tree td.dojoxGridCell img.treeExpandoLeafNoChilds {
	margin-left: -2px;
}

.aras_tree td.dojoxGridCell img.aras_item_image {
	margin-top: 3px;
}

.aras_tree .dijitTreeIndent {
	width: 23px !important;
}

.aras_tree .aras_vertical_line_for_parent {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i.gif") !important;
	background-repeat: repeat-y;
	height: 26px;
	position: absolute;
	width: inherit;
	z-index: 1;
}

.aras_tree .dojoxGridExpandoNodeWithIcon {
	position: relative;
	z-index: 10;
}

.aras_tree .dojoxGridRowTable tr:last-child .aras_vertical_line_for_parent {
	background-image: none;
}

.aras_tree .dojoxGridRow .dojoxGridRowTable tr[dojoxtreegridpath="0"]:last-child td.dojoxGridCell.dojoxGridExpandoCell div.vertical_line, .aras_tree tr[dojoxtreegridpath="0"].aras_treegrid_may_have_children td .vertical_line, .aras_tree .dojoxGridRow:last-child .dojoxGridRowTable tr.dojoxGridRowCollapsed td.dojoxGridCell.dojoxGridExpandoCell,.aras_tree .dojoxGridRow:last-child tr.aras_treegrid_last_child_row.aras_treegrid_may_have_children + tr.aras_treegrid_may_have_children td.dojoxGridCell, .aras_tree .dojoxGridRow:last-child tr.aras_treegrid_may_have_children[dojoxtreegridpath*="/"] td.dojoxGridCell.dojoxGridExpandoCell, .aras_tree tr.aras_treegrid_no_first_line.aras_treegrid_may_have_children[dojoxtreegridpath*="/"] td.dojoxGridCell.dojoxGridExpandoCell, .aras_tree tr.aras_treegrid_no_first_line.dojoxGridRowCollapsed td.dojoxGridCell, .aras_tree tr.aras_treegrid_no_first_line.aras_treegrid_may_have_children td.dojoxGridCell.dojoxGridExpandoCell, .aras_tree .dojoxGridRow:first-child .dojoxGridRowTable tr:first-child td.dojoxGridCell .dojoxGridExpandoNodeWithIcon.vertical_line, .aras_tree .dojoxGridRow:last-child tr.aras_treegrid_last_child_row.dojoxGridRowCollapsed td.dojoxGridCell {
	background-image: none !important;
}

.aras_tree tr.dojoxGridNoChildren td.dojoxGridCell img.treeExpandoLeafNoChilds {
	width: 9px !important;
}

.aras_tree tr.dojoxGridSubRowAlt, .aras_tree .dojoxGridRowOdd img.aras_treegrid_no_icon, .aras_tree .dojoxGridSubRowAlt img.aras_treegrid_no_icon {
	background-color: #F6F6F6;
}

.aras_tree td.dojoxGridCell {
	line-height: 23px;
}

.dojoxGrid.aras_tree .dojoxGridContent td.dojoxGridCellFocus a {
	margin-bottom: 1px;
}

.aras_tree th div {
	font-weight: 400;
}

.claro .aras_treegrid_method_editor.dojoxGridTreeModel .dojoxGridContent .dojoxGridCell, .aras_tree img.aras_treegrid_no_icon {
	background-color: #fff;
}

.claro .aras_tree .dojoxGridCell img {
	display: block;
}

/* end of BOM Structure, Impact Matrix and Project Plan Tree grid ==*/
.aras_tree img.aras_treegrid_no_icon {
	border: 1px solid #000000;
	margin-left: 25px;
	display: block !important;
	width: 18px !important;
	height: 18px !important;
	opacity: 0.99;
}

.aras_tree .dojoxGridRowSelected img.aras_treegrid_no_icon,.aras_tree .dojoxGridRowOver img.aras_treegrid_no_icon, .aras_tree .dojoxGridRowOdd.dojoxGridRowSelected img.aras_treegrid_no_icon, .aras_tree .dojoxGridRowOdd.dojoxGridRowOver img.aras_treegrid_no_icon, .aras_tree .dojoxGridSubRowAlt.dojoxGridRowSelected img.aras_treegrid_no_icon, .aras_tree .dojoxGridSubRowAlt.dojoxGridRowOver img.aras_treegrid_no_icon, .claro .aras_tree .dojoxGridRowEditing td {
	background-color: #DDE7F5;
}

img.aras_treegrid_icon {
	width: auto;
	height: auto;
	max-height: 18px;
	max-width: 18px;
}

.aras_tree .dijitTextBox {
	width: 100%;
}

.aras_tree .dojoxGridRowEditing .dijitTextBox input.dijitInputInner, .aras_tree .dojoxGridRowEditing div.dijitTextBox {
	margin-top: -1px !important;
	margin-left: -1px !important;
}

.aras_tree .dojoxGridRowEditing .dijitTextBox input.dijitInputInner {
	height: 18px;
}

.aras_tree.dojoxGrid div.dojoxGridRowEditing .dojoxGridRowTable tr .dojoxGridCellFocus .dijitInputInner, .aras_tree .dojoxGridRowEditing .dijitTextBox input.dijitInputInner {
	margin-left: -2px !important;
	margin-left: -1px \0/IE9 !important;
}

.aras_tree .dojoxGridRowEditing div.dijitInputField.dijitInputContainer {
	line-height: 26px !important;
}

.aras_tree .dojoxGridRowSelected.dojoxGridRowEditing .dojoxGridCellFocus img.aras_item_image,.aras_tree .dojoxGridRowEditing.dojoxGridRowOver .dojoxGridCellFocus img.aras_item_image, .aras_tree .dojoxGridRowEditing.dojoxGridRowOdd.dojoxGridRowSelected .dojoxGridCellFocus img.aras_item_image, .aras_tree .dojoxGridRowEditing.dojoxGridRowOdd.dojoxGridRowOver .dojoxGridCellFocus img.aras_item_image, .aras_tree .dojoxGridRowEditing.dojoxGridSubRowAlt.dojoxGridRowSelected .dojoxGridCellFocus img.aras_item_image, .aras_tree .dojoxGridRowEditing.dojoxGridSubRowAlt.dojoxGridRowOver .dojoxGridCellFocus img.aras_item_image, .aras_tree .dojoxGridRowEditing td.dojoxGridCellFocus{
	background-color: #fff !important;
}

.claro .aras_tree.dojoxGridTreeModel .dojoxGridContent .dojoxGridRowEditing .dojoxGridCellFocus .dojoxGridExpandoOpened .dojoxGridExpandoNode {
	background-position: -36px -1px;
}
 
.claro .aras_tree.dojoxGridTreeModel .dojoxGridContent .dojoxGridRowEditing .dojoxGridCellFocus .dojoxGridExpandoNode {
	background-position: 0px -1px;
	height: 13px !important;
}

.aras_tree .dojoxGridRow:last-child .dojoxGridRowTable tr.dojoxGridRowEditing:last-child td.dojoxGridCellFocus.dojoxGridExpandoCell div.vertical_line, .aras_tree .dojoxGridRow .dojoxGridRowTable tr.dojoxGridRowEditing:last-child td.dojoxGridCellFocus.dojoxGridExpandoCell div.vertical_line {
	background-repeat: no-repeat !important;
}

.aras_tree .dojoxGridRow .dojoxGridRowTable tr.dojoxGridRowEditing:last-child td.dojoxGridCellFocus.dojoxGridExpandoCell div.vertical_line {
	background-position: 0px 2px !important;
}

.aras_tree .dojoxGridRow:first-child .dojoxGridRowTable tr.dojoxGridRowEditing.aras_treegrid_may_have_children td.dojoxGridCellFocus div.vertical_line, .aras_tree .dojoxGridRow .dojoxGridRowTable tr[dojoxtreegridpath="0"].dojoxGridRowEditing.aras_treegrid_may_have_children:last-child td.dojoxGridCellFocus.dojoxGridExpandoCell div.vertical_line, .aras_tree tr.aras_treegrid_may_have_children.dojoxGridRowEditing.aras_treegrid_may_have_children[dojoxtreegridpath="0"] td.dojoxGridCellFocus .vertical_line {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i_half.gif") !important;
	background-position: 0px 20px !important;
	background-repeat: no-repeat !important;
}

.aras_tree .dojoxGridRow:first-child .dojoxGridRowTable tr.dojoxGridRowEditing.aras_treegrid_may_have_children.aras_treegrid_last_child_row td.dojoxGridCellFocus div.vertical_line, .aras_tree .dojoxGridRow .dojoxGridRowTable tr[dojoxtreegridpath="0"].dojoxGridRowEditing.aras_treegrid_may_have_children.aras_treegrid_last_child_row:last-child td.dojoxGridCellFocus.dojoxGridExpandoCell div.vertical_line, .aras_tree tr.aras_treegrid_may_have_children.dojoxGridRowEditing.aras_treegrid_may_have_children.aras_treegrid_last_child_row[dojoxtreegridpath="0"] td.dojoxGridCellFocus .vertical_line {
	background-image: none !important;
}

.aras_tree.dojoxGrid .dojoxGridContent .dijitComboBox .dijitArrowButtonInner {
	margin-top: 2px !important;
}

.aras_tree div.dojoxGridRow.dojoxGridRowSelected.dojoxGridRowEditing .dojoxTreeGridRowTable tr .dojoxGridCellFocus:not([bginvert="false"]) {
	background-color: #ffffff !important;
}

.aras_tree .dojoxGridRowSelected.dojoxGridRowEditing .aras_vertical_line_for_parent {
	height: 24px;
}

/* end of Tree grid */

.claro .aras_treegrid_method_editor.dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
	height: 26px;
}

.claro .dojoxGridTreeModel .dojoxGridContent .dojoxGridCell {
	height: 25px;
	background-clip: padding-box;
}

.claro .dojoxGridTreeModel .dojoxGridExpandoNode {
	margin-top: 3px;
}

.claro .dojoxGridTreeModel .dojoxGridContent td.dojoxGridCell {
	border-top: 0px none !important;
	border-left: 0 none !important;
}

.dojoxGridExpandoNode {
	float: left;
}
.claro .dojoxGridExpandoNodeWithIcon, .claro .dojoxGridTreeModel .dojoxGridNoChildren .dojoxGridExpandoNodeWithIcon {
	width: 36px !important;
}
/* end of Aras tree */

/* +++ LazyTreeGrid styles +++ */

.claro .aras_lazytreegrid_expando_with_icon {
	width: 45px !important;
}
.claro .dojoxGridTreeModel .dojoxGridNoChildren .aras_lazytreegrid_expando_with_icon {
	width: 45px !important;
}

img.aras_lazytreegrid_icon {
	width: auto;
	height: auto;
	max-height: 16px;
	max-width: 16px;
}

img.aras_lazytreegrid_no_icon {
	border: 1px solid #000000;
	display: table !important;
	width: 14px !important;
	height: 14px !important;
	background-color: #FFFFFF;
}

.claro .dojoxGridContent .aras_lazytreegrid_no_border .dojoxGridCell, .claro .dojoxGridTreeModel .dojoxGridContent .aras_lazytreegrid_no_border .dojoxGridCell {
	border: none !important;
}

.claro .dojoxGridInput {
	width: auto;
}

.claro td.dojoxGridCell .treeExpandoLeaf {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/treeExpand_leaf.gif");
	background-position: -6px 1px;
	float: left;
	height: 18px;
	vertical-align: middle;
	width: 11px;
	margin-right: 2px;
}

.claro tr.dojoxGridNoChildren td.dojoxGridCell img.treeExpandoLeafNoChilds {
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/treeExpand_leaf.gif");
	background-position: -6px -1px;
	float: left;
	height: 18px;
	vertical-align: middle;
	width: 17px;
	margin-right: 2px;
}

.claro tr.dojoxGridNoChildren td.dojoxGridCell .treeExpandoLeaf {
	background-image: url("../styles/controls/../../cbin/icons/treePathGrayDot.gif");
	background-repeat: repeat-x;
	background-position: -5px 9px;
	width: 17px;
	height: 11px;
	margin-right: 3px;
}

.claro td.dojoxGridCell img.aras_item_image {
	margin-left: 0px;
}

.claro .dojoxGridExpando {
	margin-top: 0px;
}

.claro .aras_lazytreegrid_vert_dots {
	position: absolute;
	z-index: 0;
	background-image: url("../styles/controls/../../javascript/dijit/themes/tundra/images/i.gif");
	background-repeat: repeat-y;
	background-position: 0px;
	width: 1px;
	height: 13px;
	top: 0px;
}

.claro div.dojoxGridContent .dojoxGridRow.dojoxGridRowSelected.dojoxGridRowEditing .dojoxGridRowTable tr td.dojoxGridCell.dojoxGridCellFocus {
	background-color: #fff !important;
}

.dojoxGrid.aras_tree .dojoxGridContent tr td:first-child.dojoxGridCellFocus {
	padding: 0px 2px 0px 3px !important;
	margin-right: 0px !important;
}

/* Special hack for IE10 and IE11 */
@media screen and (-ms-high-contrast: active), (-ms-high-contrast: none) {
	.dojoxGrid.aras_tree .dojoxGridContent tr td:first-child.dojoxGridCell {
		padding: 0px 2px 0px 3px !important;
	}
}

/* --- LazyTreeGrid styles --- */
/** ..\styles\controls\dropbox.css **/
.dropbox {
	position: absolute;
	top: 0;
	left: 0;
	width: 100%;
	height: 100%;
	z-index: 90;
	background-color: rgba(255, 255, 255, 0.9);
}
.dropboxInternalContainer {
	position: absolute;
	top: 50%;
	left: 0;
	right: 0;
	text-align: center;
	font-size: 14px;
	color: #a3a3a3;
	margin-top: -41px;
}
.dropboxInternalContainer img {
	height: 51px;
	display: inline;
	margin-bottom: 5px;
}
.dropboxBorder {
	position: absolute;
	right: 10px;
	bottom: 10px;
	top: 10px;
	left: 10px;
	border: 1px dashed rgb(179, 179, 179);
}

/** ..\styles\controls\popupMessages.css **/
.popupMessages{
	background: rgba(225, 225, 225, .1);
	cursor: default;
}

.popupMessages > div:hover{
	background:  rgba(255, 238, 194, 1) !important;
}
.popupMessages img{
	margin-right: 5px;
/* 	width: 16px;
	height: 16px; */
	width: auto;
	height: auto; 
	display: block; 
	max-width: 16px;
	max-height: 16px; 
}
/** ..\styles\mainWindow.css **/
/* Main window */
body {
	font-size: 12px;
	line-height: 1.4;
}

#bottom,
#BorderContainer,
#center,
#centerMiddle {
	margin: 0;
	padding: 0;
	overflow: hidden;
}
/* end of Main window */

/** ..\styles\formElements.css **/
/* form elements */
input, button, textarea {
	font: 12px Tahoma, Arial, Helvetica, sans-serif;
	padding: 2px 1px 1px 1px;
	padding-bottom: 2px \0/IE9 ;
}

textarea {
	line-height: 1.4;
	padding: 1px;
}

textarea, input {
	border: 1px solid #505050;
	color: #444;
}

input[disabled], input[readonly], textarea[disabled], textarea[readonly], .btn[disabled]:hover {
	color: #808080;
	background-color: #fff;
	border-color: #b3b3b3;
	box-shadow: none;
}

 input[readonly],textarea[readonly] {
	 color: #444444;
}

input.sys_special_readonly_prop {
	border: 1px solid #505050;
	color: #444;
	box-shadow: none;
}

input.sys_special_readonly_prop_disabled {
	color: #444444;
	background-color: #fff;
	border-color: #b3b3b3;
	box-shadow: none;
}

input[type="checkbox"].arasCheckboxOrRadio, input[type="radio"].arasCheckboxOrRadio {
	position: absolute;
	z-index: 10;
	opacity: 0;
}

input[type="checkbox"].arasCheckboxOrRadio + label:before, input[type="radio"].arasCheckboxOrRadio + label:before, .arasRadioSpec {
	content: '';
	display: inline-block;
	background: url('../styles/../images/checkbox-unchecked.svg') 0 0 no-repeat;
	width: 14px;
	height: 14px;
	margin-right: 4px;
	vertical-align: -5px;
	margin-top: 2px;
	margin-bottom: 2px;
	background-size: 14px 14px;
}

input[type="radio"].arasCheckboxOrRadio + label:before, .arasRadioSpec {
	background: url('../styles/../images/radio-bt.svg') 0 0 no-repeat;
	background-size: 14px 14px; 
}

input[type="checkbox"].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/checkbox-checked.svg');
}

input[type="checkbox"][required].arasCheckboxOrRadio + label:before {
	background-image: url('../styles/../images/checkbox-requirement.svg');
}

input[type="checkbox"][required].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/checkbox-requirement-checked.svg');
}

input[type="radio"][disabled].arasCheckboxOrRadio + label, input[type="checkbox"][disabled].arasCheckboxOrRadio + label {
	color: #6e6e6e;
}

input[type="checkbox"][disabled].arasCheckboxOrRadio + label:before {
	background-image: url('../styles/../images/checkbox-disabled.svg');
}

input[type="checkbox"][disabled].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/checkbox-disabled-checked.svg');
}

input[type="radio"].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/radio-bt-checked.svg');
}

input[type="radio"][required].arasCheckboxOrRadio + label:before {
	background-image: url('../styles/../images/radio-bt-requirement.svg');
}

input[type="radio"][required].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/radio-bt-requirement-checked.svg');
}

input[type="radio"][disabled].arasCheckboxOrRadio + label:before {
	background-image: url('../styles/../images/radio-bt-disabled.svg');
}

input[type="radio"][disabled].arasCheckboxOrRadio:checked + label:before {
	background-image: url('../styles/../images/radio-bt-disabled-checked.svg');
}

input[type="checkbox"], input[type="radio"] {
	border: 0px none;
}

input:-moz-placeholder {
	color: #8A8A8A !important;
	font-style: italic !important;
}

label {
	-moz-user-select: none;
	-ms-user-select: none;
	user-select: none;
}

.hidden {
	display: none;
}

.elipsis_button {
	width: auto;
	height: auto;
	max-height: 16px;
	max-width: 16px;
	border: none;
}

.form_btn, .btn {
	display: inline-block;
	border: none;
	color: #fff;
	background-color: #3668b1;
	padding: 3px 10px !important;
	font-size: 12px;
	line-height: 18px;
	text-align: center;
	cursor: pointer;
	vertical-align: top;
	height: 25px;
}

.btn {
	min-width: 82px;
}

.btn.cancel_button:hover {
	background-color: #777f86;
	text-decoration: none;
}

.btn.cancel_button {
	background-color: #5F6871; 
}

input.btn:focus {
	box-shadow: none;
}

.btn:hover {
	background-color: #5789d0;
	text-decoration: none;
}

.btn.disabled {
	color: #fff;
	background-color: #ccc;
	cursor: default;
}

.sys_ft_checkbox.sys_p_is_required input, .sys_ft_checkbox_list.sys_p_is_required input, .sys_ft_date.sys_p_is_required input, .sys_ft_dropdown.sys_p_is_required select, .sys_ft_file_item.sys_p_is_required input, .sys_ft_item.sys_p_is_required input, .sys_ft_listbox_multi_select.sys_p_is_required select, .sys_ft_listbox_single_select.sys_p_is_required select, .sys_ft_ml_string.sys_p_is_required input, .sys_ft_password.sys_p_is_required input, .sys_ft_radio_button_list.sys_p_is_required input, .sys_ft_text.sys_p_is_required input, .sys_ft_textarea.sys_p_is_required textarea {
	background-color: #dde7f5;
}

.sys_f_label, .sys_f_legend {
	font: normal 12px/1.4 Tahoma, Arial, Helvetica, sans-serif;
	color: #444444;
	font-weight: normal;
}

.sys_fn_item_info .sys_f_border {
	padding: 0;
}

.arasPlainLink {
	color: #3668B1;
	text-decoration: underline;
}

/* Form select */
.aras_form_select {
	border-color: #505050 !important;
	border-style: solid none solid solid;
}

.aras_form_select .DropDownArrowButtonInner {
	background: url("../styles/../images/dropdown-arrow.svg") transparent 0 bottom no-repeat !important;
	background-size: 15px 15px !important;
	margin: 0px !important;
	padding: 0px !important;
	max-height: 15px !important;
	max-width: 15px !important;
	height: 15px !important;
	width: 15px !important;
}

.aras_form_select .DropDownArrowButtonInner:hover {
	background: url("../styles/../images/dropdown-hover.svg") transparent 0 bottom no-repeat !important;
	background-size: 15px 15px !important;
}

.aras_form_select .dijitButtonNode {
	border: 0px none;
	vertical-align: bottom;
}

.claro .dijitSelectLabel {
	margin-bottom: 0px;
}

.aras_form_select .dijitSelectLabel, .aras_form_select .dijitTextBox .dijitInputInner, .aras_form_select .dijitValidationTextBox .dijitValidationContainer {
	padding: 0px;
}
/* end of Form select */
/* end of form elements */
/** ..\styles\itemProperties.css **/
/* Item properties */
.table-col {
	display: table-cell;
	height: 100%;
	vertical-align: top;
	border-right: 1px solid #D4D4D4 !important;
}

.properties-block {
	width: 200px;
	-moz-box-sizing: border-box;
	box-sizing: border-box;
	padding: 10px 15px 20px;
	background-color: transparent;
	border-style: none;
	border-top-width: 2px;
}

.properties-block .properties-block {
	padding: 0;
}

.properties-block h2 {
	margin: 0;
	font-size: 15px;
	word-break: normal;
	white-space: normal;
}

.properties-block .side-header h3 {
	margin: 0 0 10px;
	line-height: 1.4rem;
	font-size: 1.2rem;
	font-weight: normal;
	padding: 0 15px 10px 0;
	border-bottom: 1px solid #d4d4d4;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.prop-header img {
	margin: 6px 0;
	width: 45px;
	height: 45px;
}

.prop-field {
	white-space: nowrap;
}

.prop-value {
	padding-left: 1em;
}

.prop-label {
	display: inline-block;
	width: 75px;
	text-transform: capitalize;
}
/* end of Item properties */
/** ..\styles\splitter.css **/
/* Splitter */
.claro .dijitSplitter {
	background-color: transparent;
	z-index: 9999;
}

.claro .dijitSplitterH {
	border-top: 1px solid #d4d4d4;
}

.claro .dijitSplitterV {
	border-right: 1px solid #d4d4d4;
}

#leading_splitter { 
	width: 12px;
}

#leading_splitter .dijitSplitterThumb {
	left: 9px !important;
}

.claro .dijitSplitterVHover {
	background-image: none !important;
}
/* end of Splitter */
/** ..\styles\queryBuilder.css **/
div[id='QueryBuilderEditorContainer'] {
  height: 100%;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] {
  display: flex;
  align-items: flex-start;
  height: 100%;
  position: relative;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] .separator {
  width: 1px;
  height: 100%;
  z-index: 2;
  position: absolute;
  left: 135px;
  top: 0;
  pointer-events: none;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] .separator:before {
  display: block;
  content: '';
  width: 1px;
  height: 100%;
  position: relative;
  background-color: #b4b4b4;
  z-index: 1;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] .separator:after {
  display: block;
  content: '';
  width: 10px;
  height: 100%;
  position: absolute;
  background-color: white;
  left: -5px;
  top: 0;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] div[id='tree'] {
  overflow: hidden;
  display: flex;
  flex-grow: 1;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] .aras-nav {
  width: 100%;
}
div[id='QueryBuilderEditorContainer'] div[id='queryDefinitionContainer'] .aras-nav > li {
  position: relative;
  z-index: 1;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav span,
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav img {
  position: relative;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .icon-padding {
  padding-left: 2.6rem;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav-element,
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav-element:not(.aras-nav__parent) {
  padding-left: 122px;
  margin-left: 2.2rem;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav-element:before {
  position: absolute;
  left: 0;
  height: 2.2rem;
  z-index: -1;
  width: 100%;
  content: '';
}
div[id='QueryBuilderEditorContainer'] .aras-nav .aras-nav-element:hover .query-item-controls div {
  opacity: 1;
}
div[id='QueryBuilderEditorContainer'] .aras-nav__child_selected .query-item-controls div,
div[id='QueryBuilderEditorContainer'] .aras-nav__parentdiv[id='QueryBuilderEditorContainer'] .aras-nav__parent_selected .query-item-controls div {
  opacity: 1;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls {
  position: absolute;
  left: 0;
  display: inline-flex;
  justify-content: space-around;
  align-items: center;
  width: 130px;
  height: 2.2rem;
  line-height: 2.2rem;
  z-index: 666;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls:hover > div {
  opacity: 1;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__control {
  background-size: contain;
  width: 1.8rem;
  height: 1.8rem;
  opacity: 0;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__control_active {
  opacity: 1;
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__properties {
  background-image: url('../styles/../images/InputPropertyEmpty.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__properties.query-item-controls__control_active {
  background-image: url('../styles/../images/InputProperty.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__conditions {
  background-image: url('../styles/../images/CondAppliedEmpty.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__conditions.query-item-controls__control_active {
  background-image: url('../styles/../images/CondApplied.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__sort-order {
  background-image: url('../styles/../images/SortingAppliedEmpty.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__sort-order.query-item-controls__control_active {
  background-image: url('../styles/../images/SortingApplied.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__recursion-source {
  background-image: url('../styles/../images/RecursionStart.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item-controls__recursion {
  background-image: url('../styles/../images/ReusedElement.svg');
}
div[id='QueryBuilderEditorContainer'] .aras-nav .query-item_error {
  color: red;
}
div[id='QueryBuilderEditorContainer'] div[id='queryToolbar'] > div > div {
  padding: 1px 0;
}
div[id='QueryBuilderEditorContainer'] div[id='queryToolbar'] > div > div .toolbar-item {
  border: 1px solid transparent;
  box-sizing: border-box;
  width: 25px;
  height: 25px;
}
div[id='QueryBuilderEditorContainer'] div[id='queryToolbar'] > div > div .toolbar-item.toolbar-item span {
  padding: 0;
}
div[id='QueryBuilderEditorContainer'] div[id='queryToolbar'] > div > div .toolbar-item_pressed {
  border-color: #dde7f5;
}
.query-item__name,
.query-item__where-use-condition,
.query-item__join-condition {
  margin-right: 0.5rem;
}
.query-item__join-condition {
  color: #808080;
}
.query-item__join-condition::before {
  content: '[';
}
.query-item__join-condition::after {
  content: ']';
}
.query-item__where-use-condition {
  color: #71afe0;
}
.query-item__where-use-condition::before {
  content: '{';
}
.query-item__where-use-condition::after {
  content: '}';
}
.qb-relatedItems-dialog,
dialog.polyfilled.qb-relatedItems-dialog {
  width: 400px;
  height: 340px;
}
.qb-relatedItems-dialog .aras-dialog__content,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content {
  padding: 10px 20px 0 20px;
}
.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean {
  padding: 0 0 10px 5px;
}
.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean input[type='checkbox'] + span,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean input[type='checkbox'] + span {
  height: 1.1rem;
  width: 1.1rem;
}
.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean input[type='checkbox'][type='checkbox']:checked + span:before,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean input[type='checkbox'][type='checkbox']:checked + span:before {
  margin-top: -0.3rem;
}
.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean span:last-child,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .aras-form-boolean span:last-child {
  float: left;
  line-height: 1;
}
.qb-relatedItems-dialog .aras-dialog__content .search-items,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .search-items {
  padding-bottom: 10px;
}
.qb-relatedItems-dialog .aras-dialog__content .search-items__input,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .search-items__input {
  box-sizing: border-box;
  padding: 3px;
  width: 100%;
}
.qb-relatedItems-dialog .aras-dialog__content .search-items__label,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .search-items__label {
  font-size: 12px;
  margin: 0 0 5px 0;
}
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid {
  height: 200px;
}
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-header,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-header,
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-active-cell,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-active-cell {
  display: none;
}
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-cell,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-cell {
  font-size: 12px;
  border-width: 0;
}
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-levelpad:first-child:nth-last-child(2):empty:after,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-levelpad:first-child:nth-last-child(2):empty:after {
  display: none;
}
.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-icon,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content .qb-relatedItems-dialog__grid .aras-grid-row-icon {
  display: inline-block;
  margin-right: 3px;
  width: 16px;
  height: 16px;
  vertical-align: middle;
}
.qb-relatedItems-dialog .aras-dialog__content button,
dialog.polyfilled.qb-relatedItems-dialog .aras-dialog__content button {
  bottom: 10px;
  left: 50%;
  transform: translate(-50%, 0);
  position: absolute;
  width: 130px;
}
.qb-reuse-dialog {
  height: 100%;
}
.qb-reuse-dialog .tree-conntainer {
  margin: 20px 5% 0 5%;
  height: calc(100% - 130px);
  overflow: auto;
}
.qb-reuse-dialog .icon-padding {
  padding-left: 2rem;
}
.qb-reuse-dialog .aras-nav-element {
  padding-left: 0;
  margin-left: 4px;
}
.qb-reuse-dialog .query-item-controls {
  display: none;
}
.qb-reuse-dialog .aras-btn {
  margin: 20px auto;
  display: block;
  width: 150px;
}
.qb-reuse-dialog .select-block {
  border-top: 1px solid #999;
  margin: 15px 5% 0;
  position: absolute;
  width: 90%;
  height: auto;
  bottom: 0;
}
.qb-reuse-dialog .dissabled-tree-element {
  pointer-events: none;
  position: relative;
}
.qb-reuse-dialog .dissabled-tree-element:after {
  content: '';
  display: block;
  position: absolute;
  width: 100%;
  height: 100%;
  background-color: #fff;
  opacity: 0.4;
  left: 0;
  top: 0;
  z-index: 1;
}
/* Previews and editors*/
div[id='editOrder'] table {
  border-collapse: collapse;
  width: 100%;
}
div[id='editOrder'] table td {
  box-sizing: border-box;
  font-size: 0;
  width: 38%;
  padding-bottom: 0.42rem;
}
div[id='editOrder'] table td:first-child {
  width: 40%;
}
div[id='editOrder'] table td.colOrder {
  width: 12%;
}
div[id='editOrder'] table td.colDelete {
  width: 10%;
}
div[id='editOrder'] table .colOrder {
  display: table-cell;
}
div[id='editOrder'] table .colOrder > span {
  display: inline-block;
  width: 50%;
  height: 1.5rem;
  background-position: center center;
  background-size: cover;
}
div[id='editOrder'] table .colOrder > span.moveUpBtn {
  background-image: url('../styles/../images/MoveUp.svg');
}
div[id='editOrder'] table .colOrder > span.moveUpBtn:hover {
  background-image: url('../styles/../images/MoveUpActive.svg');
}
div[id='editOrder'] table .colOrder > span.moveDownBtn {
  background-image: url('../styles/../images/MoveDown.svg');
}
div[id='editOrder'] table .colOrder > span.moveDownBtn:hover {
  background-image: url('../styles/../images/MoveDownActive.svg');
}
div[id='editOrder'] table .colDelete > span {
  display: inline-block;
  width: 100%;
  height: 1.25rem;
  background: url('../styles/../images/Delete.svg') no-repeat center center / contain;
}
div[id='editOrder'] .sys_f_div_select,
div[id='editProperties'] .sys_f_div_select {
  box-sizing: border-box;
  display: inline-block;
  position: relative;
  width: 100%;
}
div[id='editOrder'] .sys_f_div_select select,
div[id='editProperties'] .sys_f_div_select select {
  width: 100%;
}
div[id='editOrder'] .sys_f_div_select,
div[id='editProperties'] .sys_f_div_select,
div[id='editOrder'] .sys_f_div_select:hover,
div[id='editProperties'] .sys_f_div_select:hover {
  background: none;
}
div[id='editOrder'] .sys_f_div_select:before,
div[id='editProperties'] .sys_f_div_select:before {
  content: '';
  position: absolute;
  border: 0.33rem solid transparent;
  border-top-color: #3668b1;
  right: 0.4rem;
  top: 0.5rem;
}
div[id='editOrder'] .sys_f_div_select:hover:after,
div[id='editProperties'] .sys_f_div_select:hover:after {
  content: '';
  position: absolute;
  width: 1.32rem;
  height: 1.32rem;
  opacity: 0.3;
  background: #5e86c1;
  top: 0;
  right: 0;
}
.img-container {
  display: inline-flex;
  position: relative;
}
.icon-with-up-arrow:before {
  content: '';
  width: 22px;
  height: 22px;
  background-image: url('../styles/../images/ReferenceGlyph.svg');
  background-size: 22px;
  position: absolute;
  left: 0;
  top: 2px;
  display: block;
}
div[id='editProperties'] .sys_f_div_select {
  float: none;
  vertical-align: middle;
  width: 90%;
}
div[id='editProperties'] img {
  padding: 0;
  display: inline-block;
  width: 5%;
  margin: 0 0 0 5%;
  vertical-align: middle;
}
.tooltip-buttons {
  clear: both;
  padding: 1.25rem 0 0 0;
  text-align: center;
}
.tooltip-buttons.hide {
  display: none;
}
.tooltip-buttons > button {
  margin: 0 0 0 5px;
  width: 9.58rem;
}
.tooltip-buttons > button:first-child {
  margin: 0;
}
div[id='showOrder'] ol {
  counter-reset: item;
}
div[id='showOrder'] ol li {
  margin: 0;
  padding: 0;
  list-style-type: none;
  counter-increment: item;
}
div[id='showOrder'] ol li:before {
  display: inline-block;
  min-width: 1rem;
  padding-right: 0.5rem;
  font-weight: bold;
  text-align: right;
  content: counter(item) '.';
}
div[id='showProperties'] ul {
  list-style: none;
}
div[id='showProperties'] ul li:before {
  content: '\2500';
  font-weight: bold;
  display: inline-block;
  margin: 0 5px 0 0;
}

/** ..\styles\dac.css **/
span[widgetid='dr_showForm'] > span > span:focus,
span[widgetid='dr_showGrid'] > span > span:focus {
  outline: none;
}
.dr-grid-container {
  height: 100%;
}
.dr-grid-container_hidden {
  visibility: hidden;
}
.dr-grid-container .dr-grid .aras-grid-active-cell {
  display: none;
}
.dr-grid-container .dr-grid .aras-grid-active-cell_editing {
  display: block;
}
.dr-grid-container .dr-grid .aras-grid-row-cell__referencing-glyph {
  position: relative;
}
.dr-grid-container .dr-grid .aras-grid-row-cell__referencing-glyph:before {
  background: url('../styles/../images/ReferenceGlyph.svg') no-repeat 0 0 / cover;
  content: '';
  width: 1.67rem;
  height: 1.67rem;
  position: absolute;
  top: 2px;
  left: 0;
}
.dr-grid-container .dr-grid .aras-grid-row-cell__icon {
  display: inline-block;
  margin-right: 3px;
  width: 1.83rem;
  height: 1.83rem;
  vertical-align: middle;
}
.destination-tree .aras-nav li {
  overflow: hidden;
  display: flex;
}
.destination-tree .aras-nav li > img {
  height: 100%;
  flex-grow: 0;
  padding-left: 5px;
}
.destination-tree-container {
  padding: 0 2px 0 6px;
}
.destination-tree-container .itemtype-info {
  overflow: hidden;
  display: flex;
  white-space: nowrap;
  text-overflow: ellipsis;
  line-height: 2.3333333rem;
  height: 2.3333333rem;
  padding: 1px;
  border-bottom: 1px solid #d4d4d4;
}
.destination-tree-container .itemtype-info img {
  height: 2.33333333rem;
  width: 1.8rem;
  flex-grow: 0;
  padding-left: 5px;
  vertical-align: middle;
  padding-right: 5px;
  -moz-user-select: none;
   -ms-user-select: none;
       user-select: none;
  max-height: 2.33333333rem;
}
.destination-tree-container .itemtype-info .arrow {
  width: 1rem;
}
.relationship-info {
  overflow: hidden;
  display: flex;
  white-space: nowrap;
  text-overflow: ellipsis;
  line-height: 2.3333333rem;
  height: 2.3333333rem;
  padding: 1px;
  border-bottom: 1px solid #d4d4d4;
}
.relationship-info img {
  height: 2.33333333rem;
  width: 1.8rem;
  flex-grow: 0;
  padding-left: 5px;
  vertical-align: middle;
  padding-right: 5px;
  -moz-user-select: none;
   -ms-user-select: none;
       user-select: none;
  max-height: 2.33333333rem;
}
.relationship-info .name {
  font-weight: bold;
  padding-right: 3px;
}
.spinner {
  width: 16px;
  height: 16px;
  position: absolute;
  bottom: 2px;
  right: 2px;
}
.spinner .double-bounce1,
.spinner.double-bounce2 {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background-color: #cc1c1c;
  opacity: 0.6;
  position: absolute;
  top: 0;
  left: 0;
  animation: sk-bounce 2s infinite ease-in-out;
}
.spinner .double-bounce2 {
  animation-delay: -1s;
}
@keyframes sk-bounce {
  0%,
  100% {
    transform: scale(0);
  }
  50% {
    transform: scale(1);
  }
}

/** ..\Modules\aras.innovator.core.EffectivityServices\Styles\EffectivityStyles.min.css **/
.effs-container{margin:0 18px}.effs-container_buttons{align-self:flex-end;margin:18px;margin-left:0;height:2.16666667rem}.effs-container_grid{margin:0;margin-left:18px}.effs-container_grid .aras-grid-header{border-top-width:0}.effs-container_grid .aras-grid-row-levelpad{display:none}.effs-container_grid .aras-form-input__wrapper.aras-form-input_invalid{width:100%}.effs-container_grid .aras-grid-head .aras-grid-head-cell:first-child,.effs-container_grid .aras-grid-row .aras-grid-row-cell:first-child{border-left-width:1px}.effs-container_grid .aras-treegrid-cell-container{height:auto}.effs-button{margin-left:3px;padding:0 1.5rem;height:2.16666667rem;line-height:2.16666667rem;font-size:8pt;font-weight:700}.effs-button_clear{color:#000;border-color:#000;background-color:#fff}.effs-toolbar-label{margin-right:4px}.effs-toolbar-item-field{display:inline-block;font-size:8pt;vertical-align:middle;padding-bottom:2px;padding-top:3px;margin-right:1px;width:130px}.effs-no-overflow{overflow:hidden}.groupContent{white-space:pre-wrap}.effs-expression-item-grid__title{padding-left:0}.effs-relationship-container{display:flex;flex-direction:row;position:absolute;overflow:hidden;width:100%;height:100%}.effs-relationship-container__iframe{display:block;border:0;overflow:hidden;min-width:100px;height:100%}.effs-relationship-container__iframe_right-splitter-pane{width:40%}.effs-relationship-container>.aras-splitter.aras-splitter_vertical{width:6px;margin-left:6px;margin-right:12px}.effs-relationship-container>.aras-splitter.aras-splitter_vertical:before,.effs-relationship-container>.aras-splitter.aras-splitter_vertical>.aras-splitter-ghost:before{display:none}