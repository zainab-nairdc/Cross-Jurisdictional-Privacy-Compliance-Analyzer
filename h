[33mcommit 19f070145fd5269b68957ea7b954489a0864eabf[m[33m ([m[1;36mHEAD[m[33m -> [m[1;32mfeature/rag-feedback-loop[m[33m)[m
Author: zainab-ncst <zainab.hammad@ncst.edu.bh>
Date:   Mon Aug 10 14:11:01 2026 +0300

    Arabic OCR routing, wizard version step, safer document deletion
    
    detect.py: route legacy-font Arabic PDFs (no ToUnicode CMap) to OCR instead of indexing Latin gibberish as English.
    
    Wizard: version lineage is its own step; a confident match is auto-selected; choose whether the replaced version is superseded or deleted.
    
    Wizard: fix ReferenceError in finalize() that hung the flow on 'Processing document', and surface non-2xx responses instead of reporting success.
    
    Delete: type-to-confirm, plus keep-or-purge for what the feedback loop learned; one shared purge path for the library and the wizard.
    
    Fix Alpine x-show stripping inline display (modal centring, Done button, status pills).
    
    'Use in comparison' preselects documents from any jurisdiction; jurisdiction labels capitalised; review step adapts to available width.
    
    Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
