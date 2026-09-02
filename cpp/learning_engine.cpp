#include <algorithm>
#include <array>
#include <iostream>
#include <sstream>
#include <string>

struct SubjectProgress {
    std::string name;
    int mastery;
    int lessonsCompleted;
    int streak;
};

class LearningEngine {
public:
    explicit LearningEngine(const std::string& studentName)
        : studentName_(studentName),
          subjects_{{
              {"Information Technology", 62, 7, 3},
              {"Mathematics", 54, 5, 2},
              {"English", 70, 9, 4},
              {"Science", 60, 6, 3}
          }} {
    }

    void logStudySession(const std::string& subjectName, int improvementPoints) {
        for (SubjectProgress& subject : subjects_) {
            if (subject.name == subjectName) {
                subject.mastery = std::min(100, subject.mastery + improvementPoints);
                subject.lessonsCompleted += 1;
                subject.streak = std::max(1, subject.streak);
                return;
            }
        }

        subjects_[0] = {subjectName, std::max(0, improvementPoints), 1, 1};
    }

    int overallProgress() const {
        int total = 0;
        for (const SubjectProgress& subject : subjects_) {
            total += subject.mastery;
        }

        return total / static_cast<int>(subjects_.size());
    }

    SubjectProgress lowestMasterySubject() const {
        SubjectProgress lowest = subjects_[0];
        for (const SubjectProgress& subject : subjects_) {
            if (subject.mastery < lowest.mastery) {
                lowest = subject;
            }
        }

        return lowest;
    }

    SubjectProgress strongestSubject() const {
        SubjectProgress strongest = subjects_[0];
        for (const SubjectProgress& subject : subjects_) {
            if (subject.mastery > strongest.mastery) {
                strongest = subject;
            }
        }

        return strongest;
    }

    std::string buildDailyPlan() const {
        std::ostringstream plan;
        SubjectProgress weak = lowestMasterySubject();
        SubjectProgress strong = strongestSubject();

        plan << "Student: " << studentName_ << "\n"
             << "Focus today: " << weak.name << " (" << weak.mastery << "% mastery)\n"
             << "Suggested task: complete 2 short exercises and review one concept summary.\n"
             << "Keep momentum: continue with " << strong.name
             << " to maintain confidence and streaks.";

        return plan.str();
    }

    void printSummary() const {
        std::cout << "\n==== Student Learning Summary ====" << "\n";
        std::cout << "Student: " << studentName_ << "\n";
        std::cout << "Overall progress: " << overallProgress() << "%\n\n";

        for (const SubjectProgress& subject : subjects_) {
            std::cout << "- " << subject.name << ": "
                      << subject.mastery << "% mastery | "
                      << subject.lessonsCompleted << " lessons | streak "
                      << subject.streak << "\n";
        }

        std::cout << "\n" << buildDailyPlan() << "\n";
    }

private:
    std::string studentName_;
    std::array<SubjectProgress, 4> subjects_;
};

int main() {
    std::string studentName;
    std::cout << "Enter student name: ";
    std::getline(std::cin, studentName);

    if (studentName.empty()) {
        studentName = "Student";
    }

    LearningEngine engine(studentName);
    engine.logStudySession("Mathematics", 12);
    engine.logStudySession("Information Technology", 8);
    engine.logStudySession("Science", 10);

    std::cout << "Welcome, " << studentName << "!\n";
    std::cout << "Your learning engine is ready.\n";
    engine.printSummary();

    return 0;
}
