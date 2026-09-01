"""
Seed script for comprehensive organization sample data.
Run: docker exec sovereignaiworkbench-backend-1 python -m scripts.seed_orgs
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import uuid
from database import engine, AsyncSessionLocal, Base
from models.data import Organization


ORGANIZATIONS = [
    {
        "name": "Apex Manufacturing Corp",
        "description": "Heavy machinery and automotive parts manufacturer with 4 production plants across India.",
        "industry": "Manufacturing",
        "location": "Pune, Maharashtra, India",
        "website": "https://nimjemfg.com",
        "founded": "2005",
        "employee_count": "2,400",
        "revenue": "$180M annually",
        "ceo": "Rajiv Kumar",
        "phone": "+91-20-2567-8900",
        "email": "info@nimjemfg.com",
        "details": {
            "employees": [
                {"name": "Rajiv Kumar", "role": "CEO & Founder", "department": "Executive", "email": "rajiv@nimjemfg.com", "phone": "+91-98765-43210"},
                {"name": "Priya Sharma", "role": "CTO", "department": "Engineering", "email": "priya.sharma@nimjemfg.com", "phone": "+91-98765-43211"},
                {"name": "Rahul Deshmukh", "role": "Plant Manager - Pune", "department": "Operations", "email": "rahul.d@nimjemfg.com", "phone": "+91-98765-43212"},
                {"name": "Anjali Patil", "role": "Head of Quality", "department": "Quality Assurance", "email": "anjali.p@nimjemfg.com", "phone": "+91-98765-43213"},
                {"name": "Vikram Joshi", "role": "CFO", "department": "Finance", "email": "vikram.j@nimjemfg.com", "phone": "+91-98765-43214"},
                {"name": "Meera Kulkarni", "role": "HR Director", "department": "Human Resources", "email": "meera.k@nimjemfg.com", "phone": "+91-98765-43215"},
                {"name": "Arjun Mehta", "role": "Supply Chain Manager", "department": "Logistics", "email": "arjun.m@nimjemfg.com", "phone": "+91-98765-43216"},
                {"name": "Sneha Rao", "role": "Safety Officer", "department": "Safety & Compliance", "email": "sneha.r@nimjemfg.com", "phone": "+91-98765-43217"},
            ],
            "departments": [
                {"name": "Executive", "head": "Rajiv Kumar", "size": 5, "description": "C-suite leadership and strategic planning"},
                {"name": "Engineering", "head": "Priya Sharma", "size": 180, "description": "R&D, product design, and process engineering"},
                {"name": "Operations", "head": "Rahul Deshmukh", "size": 1200, "description": "Plant operations, shift management, production scheduling"},
                {"name": "Quality Assurance", "head": "Anjali Patil", "size": 45, "description": "ISO 9001 compliance, inspection, and testing"},
                {"name": "Finance", "head": "Vikram Joshi", "size": 30, "description": "Accounting, budgeting, financial reporting"},
                {"name": "Human Resources", "head": "Meera Kulkarni", "size": 25, "description": "Recruitment, training, employee relations"},
                {"name": "Logistics", "head": "Arjun Mehta", "size": 60, "description": "Supply chain, procurement, inventory management"},
                {"name": "Safety & Compliance", "head": "Sneha Rao", "size": 15, "description": "OSHA compliance, incident reporting, safety training"},
            ],
            "contacts": [
                {"name": "Rajiv Kumar", "role": "CEO", "email": "rajiv@nimjemfg.com", "phone": "+91-98765-43210"},
                {"name": "Sales Team", "role": "Sales", "email": "sales@nimjemfg.com", "phone": "+91-20-2567-8901"},
                {"name": "Support Desk", "role": "Technical Support", "email": "support@nimjemfg.com", "phone": "+91-20-2567-8902"},
            ],
            "infrastructure": [
                {"name": "Pune Main Plant", "type": "Manufacturing Facility", "location": "Pune, Maharashtra", "status": "Operational", "capacity": "500 units/day"},
                {"name": "Nagpur Plant", "type": "Manufacturing Facility", "location": "Nagpur, Maharashtra", "status": "Operational", "capacity": "300 units/day"},
                {"name": "Aurangabad Plant", "type": "Stamping & Press", "location": "Aurangabad, Maharashtra", "status": "Operational", "capacity": "200 units/day"},
                {"name": "Indore Warehouse", "type": "Warehouse", "location": "Indore, Madhya Pradesh", "status": "Operational", "capacity": "10,000 sq ft"},
                {"name": "ERP System", "type": "Software", "location": "Cloud (AWS)", "status": "Active", "version": "SAP S/4HANA"},
            ],
            "financials": {
                "annual_revenue": "$180M",
                "profit_margin": "12%",
                "debt_to_equity": "0.4",
                "recent_investment": "$25M for automation upgrade (2025)",
                "top_clients": ["Tata Motors", "Mahindra & Mahindra", "Bajaj Auto"],
            },
        },
    },
    {
        "name": "DataVault Cloud Services",
        "description": "Enterprise cloud infrastructure and data center management company.",
        "industry": "Technology",
        "location": "Virginia, USA",
        "website": "https://datavault.cloud",
        "founded": "2012",
        "employee_count": "850",
        "revenue": "$420M annually",
        "ceo": "Michael Chen",
        "phone": "+1-703-555-0100",
        "email": "contact@datavault.cloud",
        "details": {
            "employees": [
                {"name": "Michael Chen", "role": "CEO", "department": "Executive", "email": "m.chen@datavault.cloud", "phone": "+1-703-555-0101"},
                {"name": "Sarah Williams", "role": "VP Engineering", "department": "Engineering", "email": "s.williams@datavault.cloud", "phone": "+1-703-555-0102"},
                {"name": "James Rodriguez", "role": "CTO", "department": "Technology", "email": "j.rodriguez@datavault.cloud", "phone": "+1-703-555-0103"},
                {"name": "Emily Park", "role": "Head of Sales", "department": "Sales", "email": "e.park@datavault.cloud", "phone": "+1-703-555-0104"},
                {"name": "David Kim", "role": "CISO", "department": "Security", "email": "d.kim@datavault.cloud", "phone": "+1-703-555-0105"},
            ],
            "departments": [
                {"name": "Executive", "head": "Michael Chen", "size": 8, "description": "Strategic leadership and corporate governance"},
                {"name": "Engineering", "head": "Sarah Williams", "size": 320, "description": "Platform development, DevOps, SRE"},
                {"name": "Sales", "head": "Emily Park", "size": 150, "description": "Enterprise sales, account management"},
                {"name": "Security", "head": "David Kim", "size": 45, "description": "Cybersecurity, compliance, SOC operations"},
                {"name": "Operations", "head": "Lisa Thompson", "size": 120, "description": "Data center operations, facility management"},
            ],
            "contacts": [
                {"name": "Michael Chen", "role": "CEO", "email": "m.chen@datavault.cloud", "phone": "+1-703-555-0101"},
                {"name": "Sales Team", "role": "Enterprise Sales", "email": "enterprise@datavault.cloud", "phone": "+1-703-555-0110"},
            ],
            "infrastructure": [
                {"name": "VA-DC1", "type": "Data Center", "location": "Ashburn, Virginia", "status": "Operational", "capacity": "5MW"},
                {"name": "VA-DC2", "type": "Data Center", "location": "Manassas, Virginia", "status": "Operational", "capacity": "8MW"},
                {"name": "TX-DC1", "type": "Data Center", "location": "Dallas, Texas", "status": "Under Construction", "capacity": "10MW"},
                {"name": "Cloud Platform", "type": "Software", "location": "Multi-region", "status": "Active", "version": "v3.2.1"},
            ],
            "financials": {
                "annual_revenue": "$420M",
                "profit_margin": "18%",
                "customers": "1,200+ enterprise clients",
                "uptime_sla": "99.999%",
            },
        },
    },
    {
        "name": "Surya Energy Systems",
        "description": "Solar and renewable energy provider operating utility-scale solar farms.",
        "industry": "Energy",
        "location": "Rajasthan, India",
        "website": "https://suryaenergy.in",
        "founded": "2015",
        "employee_count": "620",
        "revenue": "$95M annually",
        "ceo": "Dr. Amit Verma",
        "phone": "+91-141-2345-6789",
        "email": "info@suryaenergy.in",
        "details": {
            "employees": [
                {"name": "Dr. Amit Verma", "role": "CEO & Founder", "department": "Executive", "email": "amit.v@suryaenergy.in"},
                {"name": "Kavitha Nair", "role": "VP Operations", "department": "Operations", "email": "kavitha.n@suryaenergy.in"},
                {"name": "Rajesh Gupta", "role": "Head of Engineering", "department": "Engineering", "email": "rajesh.g@suryaenergy.in"},
                {"name": "Pooja Singh", "role": "CFO", "department": "Finance", "email": "pooja.s@suryaenergy.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Dr. Amit Verma", "size": 4, "description": "Leadership and strategy"},
                {"name": "Engineering", "head": "Rajesh Gupta", "size": 120, "description": "Solar panel design, grid integration"},
                {"name": "Operations", "head": "Kavitha Nair", "size": 300, "description": "Farm operations, maintenance crews"},
                {"name": "Finance", "head": "Pooja Singh", "size": 20, "description": "Financial planning, investor relations"},
            ],
            "contacts": [
                {"name": "Dr. Amit Verma", "role": "CEO", "email": "amit.v@suryaenergy.in", "phone": "+91-141-2345-6790"},
                {"name": "Project Inquiries", "role": "Business Development", "email": "projects@suryaenergy.in", "phone": "+91-141-2345-6791"},
            ],
            "infrastructure": [
                {"name": "Jodhpur Solar Farm", "type": "Solar Installation", "location": "Jodhpur, Rajasthan", "status": "Operational", "capacity": "150MW"},
                {"name": "Bikaner Solar Park", "type": "Solar Installation", "location": "Bikaner, Rajasthan", "status": "Operational", "capacity": "200MW"},
                {"name": "Jaipur Office", "type": "Office", "location": "Jaipur, Rajasthan", "status": "Active"},
            ],
            "financials": {
                "annual_revenue": "$95M",
                "total_capacity": "350MW installed",
                "carbon_offset": "500,000 tons CO2/year",
                "government_subsidies": "$12M",
            },
        },
    },
    {
        "name": "Prism Analytics Labs",
        "description": "AI-powered business intelligence and data analytics consultancy.",
        "industry": "Technology",
        "location": "Bangalore, India",
        "website": "https://prismanalytics.in",
        "founded": "2018",
        "employee_count": "340",
        "revenue": "$65M annually",
        "ceo": "Neha Kapoor",
        "phone": "+91-80-4567-8900",
        "email": "hello@prismanalytics.in",
        "details": {
            "employees": [
                {"name": "Neha Kapoor", "role": "CEO & Co-Founder", "department": "Executive", "email": "neha@prismanalytics.in"},
                {"name": "Arjun Rao", "role": "CTO & Co-Founder", "department": "Engineering", "email": "arjun.r@prismanalytics.in"},
                {"name": "Divya Menon", "role": "Head of Data Science", "department": "Data Science", "email": "divya.m@prismanalytics.in"},
                {"name": "Karthik Iyer", "role": "VP Sales", "department": "Sales", "email": "karthik.i@prismanalytics.in"},
                {"name": "Shruti Agarwal", "role": "HR Head", "department": "Human Resources", "email": "shruti.a@prismanalytics.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Neha Kapoor", "size": 5, "description": "Company leadership"},
                {"name": "Engineering", "head": "Arjun Rao", "size": 100, "description": "Platform development, ML pipelines"},
                {"name": "Data Science", "head": "Divya Menon", "size": 80, "description": "ML models, analytics, NLP"},
                {"name": "Sales", "head": "Karthik Iyer", "size": 40, "description": "Client acquisition and partnerships"},
                {"name": "Human Resources", "head": "Shruti Agarwal", "size": 15, "description": "Talent acquisition, culture"},
            ],
            "contacts": [
                {"name": "Neha Kapoor", "role": "CEO", "email": "neha@prismanalytics.in", "phone": "+91-80-4567-8901"},
                {"name": "Partnerships", "role": "Business Development", "email": "partners@prismanalytics.in", "phone": "+91-80-4567-8902"},
            ],
            "infrastructure": [
                {"name": "Bangalore HQ", "type": "Office", "location": "Koramangala, Bangalore", "status": "Active", "capacity": "400 seats"},
                {"name": "ML Training Cluster", "type": "Compute", "location": "AWS Mumbai", "status": "Active", "capacity": "32 GPU nodes"},
                {"name": "Data Lake", "type": "Storage", "location": "AWS Mumbai + GCP Delhi", "status": "Active", "capacity": "500TB"},
            ],
            "financials": {
                "annual_revenue": "$65M",
                "clients": "200+ enterprise clients",
                "funding_round": "Series B - $40M (2024)",
                "valuation": "$350M",
            },
        },
    },
    {
        "name": "MediCare Health Systems",
        "description": "Healthcare technology company providing hospital management and telemedicine solutions.",
        "industry": "Healthcare",
        "location": "Mumbai, India",
        "website": "https://medicare.health",
        "founded": "2010",
        "employee_count": "1,100",
        "revenue": "$210M annually",
        "ceo": "Dr. Rajesh Patel",
        "phone": "+91-22-6789-0123",
        "email": "info@medicare.health",
        "details": {
            "employees": [
                {"name": "Dr. Rajesh Patel", "role": "CEO & Chief Medical Officer", "department": "Executive", "email": "rajesh.p@medicare.health"},
                {"name": "Anita Sharma", "role": "CTO", "department": "Technology", "email": "anita.s@medicare.health"},
                {"name": "Dr. Sunita Reddy", "role": "Head of Clinical Operations", "department": "Clinical", "email": "sunita.r@medicare.health"},
                {"name": "Vivek Malhotra", "role": "CFO", "department": "Finance", "email": "vivek.m@medicare.health"},
            ],
            "departments": [
                {"name": "Executive", "head": "Dr. Rajesh Patel", "size": 6, "description": "Leadership and clinical governance"},
                {"name": "Technology", "head": "Anita Sharma", "size": 250, "description": "Software development, cloud, security"},
                {"name": "Clinical", "head": "Dr. Sunita Reddy", "size": 80, "description": "Clinical workflow, compliance, HIPAA"},
                {"name": "Sales & Marketing", "head": "Rohan Desai", "size": 120, "description": "Hospital sales, marketing"},
                {"name": "Finance", "head": "Vivek Malhotra", "size": 35, "description": "Finance, procurement"},
            ],
            "contacts": [
                {"name": "Dr. Rajesh Patel", "role": "CEO", "email": "rajesh.p@medicare.health", "phone": "+91-22-6789-0124"},
                {"name": "Customer Support", "role": "Support", "email": "support@medicare.health", "phone": "+91-22-6789-0125"},
            ],
            "infrastructure": [
                {"name": "Mumbai HQ", "type": "Office", "location": "Bandra Kurla Complex, Mumbai", "status": "Active"},
                {"name": "Hospital Platform", "type": "Software", "location": "AWS Mumbai", "status": "Live", "version": "v5.1"},
                {"name": "Telemedicine Platform", "type": "Software", "location": "AWS Mumbai", "status": "Live", "version": "v3.0"},
            ],
            "financials": {
                "annual_revenue": "$210M",
                "hospitals_served": "500+ hospitals",
                "patients_covered": "10M+ patients",
                "hipaa_compliant": True,
            },
        },
    },
    {
        "name": "BlueWave Logistics",
        "description": "Last-mile delivery and cold-chain logistics provider for food and pharmaceuticals.",
        "industry": "Logistics",
        "location": "Delhi, India",
        "website": "https://bluewave.in",
        "founded": "2016",
        "employee_count": "3,200",
        "revenue": "$140M annually",
        "ceo": "Sanjay Bajaj",
        "phone": "+91-11-4567-8900",
        "email": "ops@bluewave.in",
        "details": {
            "employees": [
                {"name": "Sanjay Bajaj", "role": "CEO & Founder", "department": "Executive", "email": "sanjay@bluewave.in"},
                {"name": "Nisha Agarwal", "role": "COO", "department": "Operations", "email": "nisha.a@bluewave.in"},
                {"name": "Amit Tiwari", "role": "VP Fleet", "department": "Fleet Management", "email": "amit.t@bluewave.in"},
                {"name": "Rekha Jha", "role": "CFO", "department": "Finance", "email": "rekha.j@bluewave.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Sanjay Bajaj", "size": 6, "description": "Leadership"},
                {"name": "Operations", "head": "Nisha Agarwal", "size": 800, "description": "Warehouse and delivery operations"},
                {"name": "Fleet Management", "head": "Amit Tiwari", "size": 50, "description": "Vehicle fleet, route optimization"},
                {"name": "Technology", "head": "Deepak Nair", "size": 60, "description": "Logistics platform, tracking"},
                {"name": "Finance", "head": "Rekha Jha", "size": 25, "description": "Finance and billing"},
            ],
            "contacts": [
                {"name": "Sanjay Bajaj", "role": "CEO", "email": "sanjay@bluewave.in", "phone": "+91-11-4567-8901"},
                {"name": "Operations Desk", "role": "Operations", "email": "ops@bluewave.in", "phone": "+91-11-4567-8902"},
            ],
            "infrastructure": [
                {"name": "Delhi Hub", "type": "Warehouse", "location": "Tughlakabad, Delhi", "status": "Operational", "capacity": "50,000 sq ft"},
                {"name": "Mumbai Hub", "type": "Warehouse", "location": "Navi Mumbai", "status": "Operational", "capacity": "40,000 sq ft"},
                {"name": "Cold Chain Fleet", "type": "Fleet", "location": "Pan-India", "status": "Operational", "capacity": "120 vehicles"},
                {"name": "Delivery Fleet", "type": "Fleet", "location": "Major cities", "status": "Operational", "capacity": "500 vehicles"},
            ],
            "financials": {
                "annual_revenue": "$140M",
                "daily_deliveries": "150,000+",
                "cold_chain_coverage": "12 states",
                "fleet_size": "620 vehicles",
            },
        },
    },
    {
        "name": "Vanguard Cybersecurity",
        "description": "Cybersecurity services firm providing SOC-as-a-Service and penetration testing.",
        "industry": "Cybersecurity",
        "location": "Hyderabad, India",
        "website": "https://vanguardsec.io",
        "founded": "2014",
        "employee_count": "480",
        "revenue": "$85M annually",
        "ceo": "Arvind Krishnamurthy",
        "phone": "+91-40-2345-6789",
        "email": "contact@vanguardsec.io",
        "details": {
            "employees": [
                {"name": "Arvind Krishnamurthy", "role": "CEO & Founder", "department": "Executive", "email": "arvind@vanguardsec.io"},
                {"name": "Lakshmi Iyer", "role": "CTO", "department": "Technology", "email": "lakshmi.i@vanguardsec.io"},
                {"name": "Ravi Shankar", "role": "Head of SOC", "department": "SOC", "email": "ravi.s@vanguardsec.io"},
                {"name": "Deepa Menon", "role": "VP Sales", "department": "Sales", "email": "deepa.m@vanguardsec.io"},
            ],
            "departments": [
                {"name": "Executive", "head": "Arvind Krishnamurthy", "size": 4, "description": "Leadership"},
                {"name": "SOC Operations", "head": "Ravi Shankar", "size": 180, "description": "24/7 security operations center"},
                {"name": "Penetration Testing", "head": "Vikas Reddy", "size": 60, "description": "Ethical hacking, red team"},
                {"name": "Technology", "head": "Lakshmi Iyer", "size": 80, "description": "Security platform, SIEM, SOAR"},
                {"name": "Sales", "head": "Deepa Menon", "size": 40, "description": "Enterprise sales"},
            ],
            "contacts": [
                {"name": "Arvind Krishnamurthy", "role": "CEO", "email": "arvind@vanguardsec.io", "phone": "+91-40-2345-6790"},
                {"name": "Emergency Hotline", "role": "Incident Response", "email": "soc@vanguardsec.io", "phone": "+91-40-2345-6799"},
            ],
            "infrastructure": [
                {"name": "Hyderabad SOC", "type": "Security Operations Center", "location": "HITEC City, Hyderabad", "status": "Operational", "capacity": "50 analysts"},
                {"name": "Singapore SOC", "type": "Security Operations Center", "location": "Singapore", "status": "Operational", "capacity": "20 analysts"},
                {"name": "SIEM Platform", "type": "Software", "location": "Multi-cloud", "status": "Active", "version": "Elastic SIEM 8.x"},
            ],
            "financials": {
                "annual_revenue": "$85M",
                "clients": "300+ enterprises",
                "soc_uptime": "99.99%",
                "incidents_handled": "10,000+/year",
            },
        },
    },
    {
        "name": "GreenLeaf AgriTech",
        "description": "Agricultural technology company providing precision farming and crop analytics solutions.",
        "industry": "Agriculture",
        "location": "Nashik, India",
        "website": "https://greenleaf.ag",
        "founded": "2019",
        "employee_count": "210",
        "revenue": "$30M annually",
        "ceo": "Meena Kshirsagar",
        "phone": "+91-253-2345-678",
        "email": "info@greenleaf.ag",
        "details": {
            "employees": [
                {"name": "Meena Kshirsagar", "role": "CEO & Founder", "department": "Executive", "email": "meena@greenleaf.ag"},
                {"name": "Suresh Patil", "role": "CTO", "department": "Technology", "email": "suresh.p@greenleaf.ag"},
                {"name": "Prachi Deshmukh", "role": "Head of Agronomy", "department": "Agronomy", "email": "prachi.d@greenleaf.ag"},
                {"name": "Nitin More", "role": "VP Sales", "department": "Sales", "email": "nitin.m@greenleaf.ag"},
            ],
            "departments": [
                {"name": "Executive", "head": "Meena Kshirsagar", "size": 3, "description": "Leadership"},
                {"name": "Technology", "head": "Suresh Patil", "size": 50, "description": "IoT sensors, mobile app, analytics platform"},
                {"name": "Agronomy", "head": "Prachi Deshmukh", "size": 30, "description": "Crop science, soil analysis"},
                {"name": "Sales", "head": "Nitin More", "size": 40, "description": "Farmer outreach, dealer network"},
                {"name": "Field Operations", "head": "Ramesh Kokate", "size": 60, "description": "IoT installation, farmer support"},
            ],
            "contacts": [
                {"name": "Meena Kshirsagar", "role": "CEO", "email": "meena@greenleaf.ag", "phone": "+91-253-2345-679"},
                {"name": "Farmer Helpline", "role": "Support", "email": "support@greenleaf.ag", "phone": "+91-253-2345-680"},
            ],
            "infrastructure": [
                {"name": "Nashik HQ", "type": "Office + Lab", "location": "Nashik, Maharashtra", "status": "Active"},
                {"name": "IoT Sensor Network", "type": "IoT", "location": "Maharashtra, Karnataka", "status": "Deployed", "capacity": "5,000 sensors"},
                {"name": "Analytics Platform", "type": "Software", "location": "AWS Mumbai", "status": "Active", "version": "v2.4"},
            ],
            "financials": {
                "annual_revenue": "$30M",
                "farmers_served": "25,000+",
                "crop_yield_improvement": "15-20%",
                "funding": "Series A - $8M (2023)",
            },
        },
    },
    {
        "name": "Quantum Robotics",
        "description": "Industrial automation and robotics company building warehouse and factory robots.",
        "industry": "Manufacturing",
        "location": "Chennai, India",
        "website": "https://quantumrobotics.in",
        "founded": "2017",
        "employee_count": "520",
        "revenue": "$110M annually",
        "ceo": "Dr. Krishna Prasad",
        "phone": "+91-44-3456-7890",
        "email": "info@quantumrobotics.in",
        "details": {
            "employees": [
                {"name": "Dr. Krishna Prasad", "role": "CEO & CTO", "department": "Executive", "email": "krishna@quantumrobotics.in"},
                {"name": "Asha Rani", "role": "VP Engineering", "department": "Engineering", "email": "asha.r@quantumrobotics.in"},
                {"name": "Mohan Das", "role": "Head of Sales", "department": "Sales", "email": "mohan.d@quantumrobotics.in"},
                {"name": "Lata Suresh", "role": "CFO", "department": "Finance", "email": "lata.s@quantumrobotics.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Dr. Krishna Prasad", "size": 5, "description": "Leadership and vision"},
                {"name": "Engineering", "head": "Asha Rani", "size": 200, "description": "Robotics, mechatronics, AI/ML"},
                {"name": "Sales", "head": "Mohan Das", "size": 60, "description": "Enterprise automation sales"},
                {"name": "Field Service", "head": "Sunil Kumar", "size": 80, "description": "Installation, maintenance, support"},
                {"name": "Finance", "head": "Lata Suresh", "size": 20, "description": "Finance, procurement"},
            ],
            "contacts": [
                {"name": "Dr. Krishna Prasad", "role": "CEO", "email": "krishna@quantumrobotics.in", "phone": "+91-44-3456-7891"},
                {"name": "Sales Team", "role": "Sales", "email": "sales@quantumrobotics.in", "phone": "+91-44-3456-7892"},
            ],
            "infrastructure": [
                {"name": "Chennai R&D Center", "type": "R&D Lab", "location": "Tidel Park, Chennai", "status": "Active"},
                {"name": "Chennai Factory", "type": "Manufacturing", "location": "Sriperumbudur, Chennai", "status": "Operational", "capacity": "200 robots/year"},
                {"name": "Demo Center", "type": "Showroom", "location": "Mumbai", "status": "Active"},
            ],
            "financials": {
                "annual_revenue": "$110M",
                "robots_deployed": "3,000+",
                "clients": "150+ factories",
                "funding": "Series C - $60M (2024)",
            },
        },
    },
    {
        "name": "CloudNest SaaS",
        "description": "Cloud-native SaaS platform for project management and team collaboration.",
        "industry": "Technology",
        "location": "Singapore",
        "website": "https://cloudnest.io",
        "founded": "2020",
        "employee_count": "280",
        "revenue": "$55M annually",
        "ceo": "Wei Lin Tan",
        "phone": "+65-6789-0123",
        "email": "hello@cloudnest.io",
        "details": {
            "employees": [
                {"name": "Wei Lin Tan", "role": "CEO & Co-Founder", "department": "Executive", "email": "wei@cloudnest.io"},
                {"name": "Raj Malhotra", "role": "CTO & Co-Founder", "department": "Engineering", "email": "raj.m@cloudnest.io"},
                {"name": "Yuki Sato", "role": "VP Product", "department": "Product", "email": "yuki.s@cloudnest.io"},
                {"name": "Anna Lee", "role": "VP Marketing", "department": "Marketing", "email": "anna.l@cloudnest.io"},
            ],
            "departments": [
                {"name": "Executive", "head": "Wei Lin Tan", "size": 4, "description": "Leadership"},
                {"name": "Engineering", "head": "Raj Malhotra", "size": 120, "description": "Backend, frontend, DevOps, QA"},
                {"name": "Product", "head": "Yuki Sato", "size": 20, "description": "Product management, design, UX"},
                {"name": "Marketing", "head": "Anna Lee", "size": 30, "description": "Growth, content, brand"},
                {"name": "Customer Success", "head": "Maria Santos", "size": 40, "description": "Onboarding, support, retention"},
            ],
            "contacts": [
                {"name": "Wei Lin Tan", "role": "CEO", "email": "wei@cloudnest.io", "phone": "+65-6789-0124"},
                {"name": "Support Team", "role": "Support", "email": "support@cloudnest.io", "phone": "+65-6789-0125"},
            ],
            "infrastructure": [
                {"name": "Singapore HQ", "type": "Office", "location": "One Raffles Place, Singapore", "status": "Active"},
                {"name": "AWS ap-southeast-1", "type": "Cloud", "location": "Singapore", "status": "Active", "capacity": "Multi-AZ"},
                {"name": "GCP asia-south1", "type": "Cloud", "location": "Mumbai", "status": "Active", "capacity": "Multi-AZ"},
            ],
            "financials": {
                "annual_revenue": "$55M",
                "arr": "$55M",
                "customers": "8,000+ teams",
                "churn_rate": "3.2%",
                "funding": "Series B - $30M (2024)",
            },
        },
    },
    {
        "name": "Titan Steel Industries",
        "description": "Steel fabrication and structural engineering company for infrastructure projects.",
        "industry": "Manufacturing",
        "location": "Jamshedpur, India",
        "website": "https://titansteel.in",
        "founded": "1998",
        "employee_count": "4,500",
        "revenue": "$520M annually",
        "ceo": "Harish Agarwal",
        "phone": "+91-657-234-5678",
        "email": "info@titansteel.in",
        "details": {
            "employees": [
                {"name": "Harish Agarwal", "role": "Chairman & MD", "department": "Executive", "email": "harish.a@titansteel.in"},
                {"name": "Sanjeev Mishra", "role": "CEO", "department": "Executive", "email": "sanjeev.m@titansteel.in"},
                {"name": "Priti Singh", "role": "VP Operations", "department": "Operations", "email": "priti.s@titansteel.in"},
                {"name": "Mohan Krishna", "role": "Head of Sales", "department": "Sales", "email": "mohan.k@titansteel.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Harish Agarwal", "size": 8, "description": "Board and C-suite leadership"},
                {"name": "Operations", "head": "Priti Singh", "size": 2500, "description": "Steel manufacturing, quality control"},
                {"name": "Sales", "head": "Mohan Krishna", "size": 80, "description": "Infrastructure project sales"},
                {"name": "Engineering", "head": "Rakesh Verma", "size": 150, "description": "Structural engineering, design"},
                {"name": "Safety", "head": "Anand Sharma", "size": 40, "description": "Industrial safety, environmental compliance"},
            ],
            "contacts": [
                {"name": "Harish Agarwal", "role": "Chairman", "email": "harish.a@titansteel.in", "phone": "+91-657-234-5679"},
                {"name": "Project Sales", "role": "Sales", "email": "projects@titansteel.in", "phone": "+91-657-234-5680"},
            ],
            "infrastructure": [
                {"name": "Jamshedpur Steel Plant", "type": "Steel Mill", "location": "Jamshedpur, Jharkhand", "status": "Operational", "capacity": "1.2M tons/year"},
                {"name": "Kalinganagar Plant", "type": "Steel Mill", "location": "Kalinganagar, Odisha", "status": "Operational", "capacity": "800K tons/year"},
                {"name": "Fabrication Yard", "type": "Workshop", "location": "Jamshedpur", "status": "Operational", "capacity": "50,000 sq ft"},
            ],
            "financials": {
                "annual_revenue": "$520M",
                "production_capacity": "2M tons/year",
                "clients": "Govt. of India, L&T, Tata Projects",
                "iso_certified": "ISO 9001, ISO 14001, OHSAS 18001",
            },
        },
    },
    {
        "name": "AeroSense Aviation",
        "description": "Drone-based inspection and monitoring services for infrastructure and agriculture.",
        "industry": "Aerospace",
        "location": "Bangalore, India",
        "website": "https://aerosense.in",
        "founded": "2021",
        "employee_count": "95",
        "revenue": "$12M annually",
        "ceo": "Group Captain (Retd.) Vikram Singh",
        "phone": "+91-80-5678-9012",
        "email": "fly@aerosense.in",
        "details": {
            "employees": [
                {"name": "Group Captain (Retd.) Vikram Singh", "role": "CEO & Founder", "department": "Executive", "email": "vikram@aerosense.in"},
                {"name": "Nikhil Sharma", "role": "CTO", "department": "Technology", "email": "nikhil.s@aerosense.in"},
                {"name": "Divya Raghavan", "role": "Head of Operations", "department": "Operations", "email": "divya.r@aerosense.in"},
            ],
            "departments": [
                {"name": "Executive", "head": "Vikram Singh", "size": 3, "description": "Leadership"},
                {"name": "Technology", "head": "Nikhil Sharma", "size": 25, "description": "Drone hardware, software, AI vision"},
                {"name": "Operations", "head": "Divya Raghavan", "size": 40, "description": "Drone pilots, mission planning"},
                {"name": "Sales", "head": "Prakash Reddy", "size": 12, "description": "Enterprise and government sales"},
            ],
            "contacts": [
                {"name": "Vikram Singh", "role": "CEO", "email": "vikram@aerosense.in", "phone": "+91-80-5678-9013"},
                {"name": "Mission Control", "role": "Operations", "email": "ops@aerosense.in", "phone": "+91-80-5678-9014"},
            ],
            "infrastructure": [
                {"name": "Bangalore HQ", "type": "Office + Workshop", "location": "HSR Layout, Bangalore", "status": "Active"},
                {"name": "Drone Fleet", "type": "Equipment", "location": "Pan-India", "status": "Operational", "capacity": "45 drones"},
                {"name": "AI Processing Lab", "type": "Compute", "location": "Bangalore", "status": "Active", "capacity": "8 GPU workstations"},
            ],
            "financials": {
                "annual_revenue": "$12M",
                "missions_completed": "2,500+",
                "clients": "NHAI, Border Roads, State Agricultural Depts",
                "funding": "Seed - $3M (2022)",
            },
        },
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, delete
        # Clear existing orgs
        await db.execute(delete(Organization))
        await db.flush()

        for org_data in ORGANIZATIONS:
            details = org_data.pop("details", {})
            org = Organization(
                id=str(uuid.uuid4()),
                owner_id="121f473a-3504-4ccb-8d3b-14db79ccea7b",  # admin user
                details_json=json.dumps(details) if details else None,
                **org_data,
            )
            db.add(org)

        await db.commit()
        print(f"Seeded {len(ORGANIZATIONS)} organizations with full details.")


if __name__ == "__main__":
    asyncio.run(seed())
