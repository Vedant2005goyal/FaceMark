-- FaceMark schema + seed data. Runnable as-is:
--   mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS attendance_system"
--   mysql -u root -p attendance_system < schema.sql
-- docker-compose also mounts this file into the MySQL init directory.

-- Entities
CREATE TABLE User (
    User_ID INT PRIMARY KEY AUTO_INCREMENT,
    Name VARCHAR(100) NOT NULL,
    Email VARCHAR(100) UNIQUE NOT NULL,   -- Used for login
    Contact_No VARCHAR(10),
    User_Role VARCHAR(10) NOT NULL        -- 'Student' or 'Faculty'
);

CREATE TABLE Class (
    Class_ID INT PRIMARY KEY,
    Class_Name VARCHAR(50) NOT NULL,
    Year INT,
    Department VARCHAR(30) NOT NULL
);

CREATE TABLE Students (
    User_ID INT PRIMARY KEY,
    Roll_no VARCHAR(9) UNIQUE,
    Parent_Email VARCHAR(100),
    Class_ID INT,
    FOREIGN KEY (User_ID) REFERENCES User(User_ID),
    FOREIGN KEY (Class_ID) REFERENCES Class(Class_ID)
);

CREATE TABLE Faculty (
    User_ID INT PRIMARY KEY,
    Department VARCHAR(50),
    Faculty_Role VARCHAR(20) DEFAULT 'Faculty',  -- e.g. 'Professor', 'HOD'
    FOREIGN KEY (User_ID) REFERENCES User(User_ID)
);

CREATE TABLE Subject (
    Subject_ID INT PRIMARY KEY AUTO_INCREMENT,
    Subject_Name VARCHAR(100) NOT NULL,
    Subject_Code VARCHAR(20) UNIQUE,
    Credits INT DEFAULT 3,
    User_ID INT,                     -- Faculty who teaches it
    Class_ID INT,
    Semester INT,
    Is_Active BOOLEAN DEFAULT TRUE,  -- Scheduler only checks active subjects
    FOREIGN KEY (User_ID) REFERENCES Faculty(User_ID),
    FOREIGN KEY (Class_ID) REFERENCES Class(Class_ID)
);

-- Many-to-many: which students take which subjects
CREATE TABLE Student_Subject (
    User_ID INT,
    Subject_ID INT,
    PRIMARY KEY (User_ID, Subject_ID),
    FOREIGN KEY (User_ID) REFERENCES Students(User_ID),
    FOREIGN KEY (Subject_ID) REFERENCES Subject(Subject_ID)
);

-- Face recognition and attendance
CREATE TABLE Face_Embeddings (
    Face_ID INT PRIMARY KEY AUTO_INCREMENT,
    User_ID INT NOT NULL,
    Face_Encoding TEXT NOT NULL,  -- JSON list of the 128-d encoding; several rows per user allowed
    Photo_Path VARCHAR(255),
    Created_At TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (User_ID) REFERENCES User(User_ID)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_user (User_ID)
);

CREATE TABLE Attendance_Session (
    Session_ID INT PRIMARY KEY AUTO_INCREMENT,
    Subject_ID INT NOT NULL,
    Session_Date DATE NOT NULL,
    Start_Time TIME NOT NULL,
    End_Time TIME NOT NULL,
    Session_Type VARCHAR(20) DEFAULT 'Lecture',  -- 'Lecture', 'Lab', 'Tutorial'
    Status VARCHAR(20) DEFAULT 'Scheduled',      -- 'Scheduled', 'Ongoing', 'Completed'
    Created_By INT,                              -- Faculty who created the session
    FOREIGN KEY (Subject_ID) REFERENCES Subject(Subject_ID),
    FOREIGN KEY (Created_By) REFERENCES Faculty(User_ID),
    INDEX idx_subject_date (Subject_ID, Session_Date),
    CONSTRAINT unique_session UNIQUE (Subject_ID, Session_Date, Start_Time)
);

CREATE TABLE Attendance (
    Attendance_ID INT PRIMARY KEY AUTO_INCREMENT,
    Session_ID INT NOT NULL,
    User_ID INT NOT NULL,                              -- Student's User_ID
    Subject_ID INT NOT NULL,
    Date DATE NOT NULL,
    Check_In_Time DATETIME,                            -- NULL for Absent rows
    Status VARCHAR(10) NOT NULL,                       -- 'Present', 'Late', 'Absent'
    Marked_By VARCHAR(20) DEFAULT 'Face Recognition',  -- 'Face Recognition', 'System', 'Manual'
    FOREIGN KEY (Session_ID) REFERENCES Attendance_Session(Session_ID),
    FOREIGN KEY (User_ID) REFERENCES Students(User_ID),
    FOREIGN KEY (Subject_ID) REFERENCES Subject(Subject_ID),
    UNIQUE KEY (User_ID, Session_ID)                   -- One attendance row per student per session
);

CREATE TABLE Attendance_Settings (
    Setting_ID INT PRIMARY KEY AUTO_INCREMENT,
    Setting_Key VARCHAR(50) UNIQUE NOT NULL,
    Setting_Value VARCHAR(100) NOT NULL,
    Description TEXT,
    Updated_At TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Seed data
INSERT INTO Attendance_Settings (Setting_Key, Setting_Value, Description) VALUES
('late_threshold_minutes', '10', 'Minutes after start time to mark as late'),
('min_attendance_percentage', '75', 'Minimum required attendance percentage');

INSERT INTO User (User_ID, Name, Email, Contact_No, User_Role) VALUES
(1, 'Angelina Jolie', 'ajolie@thapar.edu', '9876543210', 'Student'),
(2, 'Brad Pitt', 'bpitt@thapar.edu', '9876543211', 'Student'),
(3, 'Denzel Washington', 'dwashington@thapar.edu', '9876543212', 'Faculty'),
(4, 'Hugh Jackman', 'hjackman@thapar.edu', '9876543213', 'Student'),
(5, 'Jennifer Lawrence', 'jlawrence@thapar.edu', '9876543214', 'Student'),
(6, 'Johnny Depp', 'jdepp@thapar.edu', '9876543215', 'Student'),
(7, 'Kate Winslet', 'kwinslet@thapar.edu', '9876543216', 'Faculty'),
(8, 'Leonardo DiCaprio', 'ldicaprio@thapar.edu', '9876543217', 'Student'),
(9, 'Megan Fox', 'mfox@thapar.edu', '9876543218', 'Student'),
(10, 'Natalie Portman', 'nportman@thapar.edu', '9876543219', 'Student'),
(11, 'Nicole Kidman', 'nkidman@thapar.edu', '9876543220', 'Student'),
(12, 'Robert Downey Jr', 'rdowney@thapar.edu', '9876543221', 'Student'),
(13, 'Sandra Bullock', 'sbullock@thapar.edu', '9876543222', 'Student'),
(14, 'Scarlett Johansson', 'sjohansson@thapar.edu', '9876543223', 'Student'),
(15, 'Tom Cruise', 'tcruise@thapar.edu', '9876543224', 'Student'),
(16, 'Tom Hanks', 'thanks@thapar.edu', '9876543225', 'Faculty'),
(17, 'Will Smith', 'wsmith@thapar.edu', '9876543226', 'Student'),
(18, 'Osho', 'rajneeshpuram@thapar.edu', '9876535871', 'Faculty'),
(19, 'Khalil Gibran', 'prophet@thapar.edu', '9682535871', 'Faculty'),
(20, 'Aditya Gupta', 'aditya@thapar.edu', '9352196565', 'Student'),
(21, 'Vedant Goyal', 'vgoyal@thapar.edu', '8571027278', 'Student'),
(22, 'Rushil Upadhyay', 'rupadh@thapar.edu', '1234567890', 'Student'),
(23, 'Nikunj Garg', 'nikunj@thapar.edu', '9644863454', 'Student'),
(24, 'Kusham Lata', 'kusham@thapar.edu', '8899248891', 'Student');

INSERT INTO Class (Class_ID, Class_Name, Year, Department) VALUES
(101, '1S01', 1, 'COE'),
(102, '1S02', 1, 'COE'),
(103, '2S01', 2, 'COE'),
(104, '2S02', 2, 'COE'),
(105, '3S01', 3, 'COE'),
(106, '3S02', 3, 'COE'),
(107, '4S01', 4, 'COE'),
(108, '4S02', 4, 'COE'),
(111, '1S03', 1, 'EEC'),
(112, '1S04', 1, 'EEC'),
(113, '2S03', 2, 'EEC'),
(114, '3S03', 3, 'EEE'),
(115, '4S03', 4, 'EEC'),
(121, '1S05', 1, 'ME'),
(122, '1S06', 1, 'ME'),
(123, '2S04', 2, 'ME'),
(124, '3S04', 3, 'ME'),
(125, '4S04', 4, 'ME'),
(131, '1S07', 1, 'CE'),
(132, '2S05', 2, 'CE'),
(133, '3S05', 3, 'CE'),
(134, '4S05', 4, 'CE'),
(141, '1S08', 1, 'CHE'),
(142, '2S06', 2, 'CHE'),
(151, '1S09', 1, 'BT');

INSERT INTO Faculty (User_ID, Faculty_Role, Department) VALUES
(3, 'Professor', 'COE'),
(7, 'Associate Professor', 'ECE'),
(16, 'Professor', 'ME');

INSERT INTO Subject (Subject_ID, Subject_Name, Subject_Code, User_ID, Class_ID, Credits, Semester) VALUES
(1001, 'Introduction to Programming', 'UCS101', 3, 101, 4, 1),
(1002, 'Basic Electrical Engineering', 'UES101', 7, 101, 3, 1),
(1003, 'Physics', 'UPH101', 16, 101, 3, 2),
(1005, 'Data Structures', 'UCS310', 3, 103, 4, 3),
(1007, 'Operating Systems', 'UCS410', 3, 103, 4, 4),
(1008, 'Computer Architecture', 'UCS411', 7, 103, 3, 4),
(1009, 'Database Management Systems', 'UCS510', 16, 105, 3, 5),
(1010, 'Software Engineering', 'UCS511', 3, 105, 3, 5),
(1011, 'Computer Networks', 'UCS610', 16, 105, 4, 6),
(1013, 'Machine Learning', 'UCS710', 7, 107, 3, 7),
(1014, 'Capstone', 'UCS799', 16, 107, 4, 7),
(1016, 'Basic Electronics', 'UEC101', 7, 111, 4, 1),
(1018, 'Analog Electronics', 'UEC310', 7, 113, 3, 3),
(1020, 'Communication Systems', 'UEC510', 7, 114, 3, 5),
(1022, 'Engineering Drawing', 'UME101', 16, 121, 2, 1),
(1024, 'Thermodynamics', 'UME310', 16, 123, 4, 3),
(1026, 'Fluid Mechanics', 'UME510', 16, 124, 3, 5),
(1027, 'Heat Transfer', 'UME610', 16, 124, 4, 6),
(1028, 'Surveying', 'UCE310', 3, 132, 3, 3);

INSERT INTO Students (User_ID, Roll_no, Parent_Email, Class_ID) VALUES
(1, '10230101', 'parent.jolie@gmail.com', 101),
(2, '10230102', 'parent.pitt@gmail.com', 102),
(4, '10230301', 'parent.jackman@gmail.com', 111),
(5, '10230302', 'parent.lawrence@gmail.com', 112),
(6, '10230501', 'parent.depp@gmail.com', 121),
(8, '10220101', 'parent.dicaprio@gmail.com', 103),
(9, '10220102', 'parent.fox@gmail.com', 104),
(10, '10220301', 'parent.portman@gmail.com', 113),
(11, '10220501', 'parent.kidman@gmail.com', 123),
(12, '10220701', 'parent.downey@gmail.com', 132),
(13, '10210101', 'parent.bullock@gmail.com', 105),
(14, '10210102', 'parent.johansson@gmail.com', 106),
(15, '10210301', 'parent.cruise@gmail.com', 114),
(17, '10210501', 'parent.smith@gmail.com', 124),
(20, '10200101', 'parent.aditya@thapar.edu', 107),
(21, '10200102', 'parent.vedant@thapar.edu', 107),
(22, '10200103', 'parent.rushil@thapar.edu', 108),
(23, '10200104', 'parent.nikunj@thapar.edu', 108),
(24, '10200105', 'parent.kusham@thapar.edu', 108);

-- Enrol each student in their class's subjects, and the five real students in DBMS (1009)
INSERT INTO Student_Subject (User_ID, Subject_ID)
SELECT st.User_ID, sub.Subject_ID FROM Students st JOIN Subject sub ON sub.Class_ID = st.Class_ID;
INSERT IGNORE INTO Student_Subject (User_ID, Subject_ID) VALUES
(20, 1009), (21, 1009), (22, 1009), (23, 1009), (24, 1009);
