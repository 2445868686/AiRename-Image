# main.py
import sys
from PyQt5.QtWidgets import QApplication
from ui import ConfigGUI # Import the main GUI class from ui.py

def main():
    app = QApplication(sys.argv)
    # You can set a global application style here if desired, e.g.:
    # app.setStyle("Fusion") 
    
    ex = ConfigGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
