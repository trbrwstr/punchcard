       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVLOOK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INVENTORY-FILE ASSIGN TO "inventory.dat".
       DATA DIVISION.
       FILE SECTION.
       FD  INVENTORY-FILE.
       01  INVENTORY-RECORD.
           05 ITEM-CODE PIC X(10).
           05 ITEM-COUNT PIC 9(05).
       WORKING-STORAGE SECTION.
       01  WS-SEARCH-CODE PIC X(10) VALUE "A100".
       01  WS-FOUND PIC X VALUE "N".
       01  WS-PRICE PIC 9(05)V99 VALUE ZERO.
       PROCEDURE DIVISION.
       START-LOOKUP.
           OPEN INPUT INVENTORY-FILE.
           PERFORM READ-NEXT.
           CLOSE INVENTORY-FILE.
           STOP RUN.
       READ-NEXT.
           READ INVENTORY-FILE.
           IF ITEM-CODE = WS-SEARCH-CODE
               MOVE "Y" TO WS-FOUND
               COMPUTE WS-PRICE = ITEM-COUNT * 1.25
           ELSE
               GO TO READ-NEXT
           END-IF.
       PRICE-BAND.
           EVALUATE WS-FOUND
               WHEN "Y"
                   ADD 10 TO ITEM-COUNT
               WHEN OTHER
                   SUBTRACT 1 FROM ITEM-COUNT
           END-EVALUATE.
           GOBACK.
